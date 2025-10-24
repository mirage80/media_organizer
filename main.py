#!/usr/bin/env python3
"""
Media Organizer Pipeline - Main Orchestrator
Replaces top.ps1 with a pure Python implementation.
"""

import os
import sys
import subprocess
import signal
from pathlib import Path
import re
from typing import Dict, List, Any, Optional
import argparse
import re

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utilities import get_config, MediaOrganizerConfig, setup_pipeline_logging, get_script_logger, create_logger_function, ProgressBarManager, show_progress_bar, stop_graphical_progress_bar


class PipelineOrchestrator:
    """
    Main pipeline orchestrator for the Media Organizer.
    Manages phase execution, progress tracking, and error handling.
    """
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize the pipeline orchestrator.
        
        Args:
            config_file: Optional path to config file
        """
        self.config = get_config(config_file)
        self.logger = None
        self.progress_manager = None
        self.current_phase_index = 0
        self.total_phases = 0
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        if self.logger:
            self.logger.info("Received shutdown signal. Cleaning up...")
        
        if self.progress_manager:
            self.progress_manager.stop()
        
        sys.exit(0)
    
    def _setup_logging(self) -> None:
        """Setup logging for the pipeline."""
        log_directory = self.config.get_paths().get('logDirectory', 'Logs')
        self.logger = get_script_logger(log_directory, 'main', '')
        self.log = create_logger_function(self.logger)
        
    def _validate_environment(self) -> bool:
        """
        Validate the environment and required tools.
        
        Returns:
            True if environment is valid, False otherwise
        """
        self.log("INFO", "--- Main Pipeline Started ---")
        
        # Validate tools
        missing_tools = self.config.validate_tools()
        if missing_tools:
            for tool in missing_tools:
                self.log("CRITICAL", f"Required tool not found: {tool}")
            self.log("CRITICAL", "Aborting due to missing tools.")
            return False
        
        # Ensure directories exist
        self.config.ensure_directories()
        
        # Setup environment variables
        self.config.setup_environment_variables()
        
        return True
    
    def _execute_python_script(self, script_path: str, step_name: str) -> bool:
        """
        Execute a Python script with progress tracking.
        
        Args:
            script_path: Path to the Python script
            phase_name: Name of the phase for logging
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare command - pass config object as JSON
            python_exe = sys.executable
            import json
            config_json = json.dumps(self.config.config_data, indent=None)
            cmd = [python_exe, script_path, "--config-json", config_json]
            
            self.log("DEBUG", f"Executing: {' '.join(cmd)}")
            
            # Start process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor output for progress updates
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                
                if output:
                    output = output.strip()
                    
                    # Check for progress updates
                    if output.startswith('PROGRESS:'):
                        try:
                            # Format: PROGRESS:percentage|status
                            parts = output[9:].split('|', 1)
                            if len(parts) == 2:
                                percent = int(parts[0])
                                status = parts[1]
                                self.progress_manager.update_subtask(percent, status)
                        except (ValueError, IndexError):
                            pass
                    elif output.startswith(('DEBUG:', 'INFO:', 'WARNING:', 'ERROR:', 'CRITICAL:')):
                        # Forward log messages
                        level, message = output.split(':', 1)
                        self.log(level.strip(), f"PY: {message.strip()}")
                    else:
                        # Regular output
                        self.log("DEBUG", f"PY_STDOUT: {output}")
            
            # Wait for completion and get return code
            return_code = process.wait()
            
            # Log any errors
            stderr_output = process.stderr.read()
            if stderr_output:
                for line in stderr_output.strip().split('\n'):
                    if line:
                        self.log("ERROR", f"PY_STDERR: {line}")
            
            if return_code != 0:
                self.log("ERROR", f"Python script '{script_path}' failed with exit code {return_code}")
                return False
            
            return True
            
        except Exception as e:
            self.log("ERROR", f"Error running Python script '{script_path}': {e}")
            return False
    
    def _execute_powershell_script(self, script_path: str, args: Dict[str, Any], step_name: str) -> bool:
        """
        Execute a PowerShell script (for backward compatibility during transition).
        
        Args:
            script_path: Path to the PowerShell script
            args: Arguments to pass to the script
            phase_name: Name of the phase for logging
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Build PowerShell command
            cmd = ['pwsh', '-ExecutionPolicy', 'Bypass', '-File', script_path]
            
            # Add arguments
            for key, value in args.items():
                cmd.extend([f'-{key}', str(value)])
            
            self.log("DEBUG", f"Executing PowerShell: {' '.join(cmd)}")
            
            # Execute
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            # Log output
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        self.log("DEBUG", f"PS_STDOUT: {line}")
            
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    if line:
                        self.log("ERROR", f"PS_STDERR: {line}")
            
            if result.returncode != 0:
                self.log("ERROR", f"PowerShell script '{script_path}' failed with exit code {result.returncode}")
                return False
            
            return True
            
        except Exception as e:
            self.log("ERROR", f"Error running PowerShell script '{script_path}': {e}")
            return False
    
    def _execute_step(self, step: Dict[str, Any], phase_number: int = 0) -> bool:
        """
        Execute a single pipeline step.
        
        Args:
            step: Step configuration dictionary
            phase_number: Current phase number (0 for non-phase steps like counter)
            
        Returns:
            True if successful, False otherwise
        """
        step_name = step.get('Name', 'Unknown')
        step_type = step.get('Type', 'Unknown')
        step_path = step.get('Path', '')
        step_args = step.get('Args', [])
        is_interactive = step.get('Interactive', False)
        
        # --- Determine Step Number from Path ---
        step_number_from_path = 0
        match = re.search(r'step(\d+)', step_path)
        if match:
            step_number_from_path = int(match.group(1))

        is_counter = 'counter.py' in step_path or step_number_from_path == 0
        
        if is_counter:
            self.log("INFO", f"Running utility: {step_name}")
            os.environ['CURRENT_STEP'] = '0'
        else:
            self.log("INFO", f"Starting Phase {phase_number}/{self.total_phases}: {step_name}")
            os.environ['CURRENT_STEP'] = str(step_number_from_path)
        
        # Resolve arguments
        resolved_args = self.config.resolve_step_arguments(step_args)
        
        # Set environment variables for Python scripts
        os.environ['CONFIG_FILE_PATH'] = str(self.config.config_file)
        
        # Handle interactive steps
        if is_interactive:
            self.progress_manager.send_to_back()
        
        # Execute based on type
        success = False
        if step_type == 'Python':
            script_path = PROJECT_ROOT / step_path
            success = self._execute_python_script(str(script_path), step_name)
        elif step_type == 'PowerShell':
            script_path = PROJECT_ROOT / step_path
            args_dict = resolved_args if isinstance(resolved_args, dict) else {}
            success = self._execute_powershell_script(str(script_path), args_dict, step_name)
        else:
            self.log("ERROR", f"Unknown step type: {step_type}")
            return False
        
        # Restore progress bar for interactive steps
        if is_interactive:
            self.progress_manager.bring_to_front()
        
        if success:
            if is_counter:
                self.log("INFO", f"Completed utility: {step_name}")
            else:
                self.log("INFO", f"Completed Phase {phase_number}/{self.total_phases}: {step_name}")
        else:
            if is_counter:
                self.log("ERROR", f"Failed utility: {step_name}")
            else:
                self.log("ERROR", f"Failed Phase {phase_number}/{self.total_phases}: {step_name}")
        
        return success
    
    def run(self, resume_from: Optional[int] = None) -> bool:
        """
        Run the entire pipeline.
        
        Args:
            resume_from: Optional phase number to resume from
            
        Returns:
            True if pipeline completed successfully, False otherwise
        """
        try:
            # Setup logging
            self._setup_logging()
            
            # Validate environment
            if not self._validate_environment():
                return False
            
            # Get all enabled steps and count actual phases (excluding counter)
            all_enabled_steps = self.config.get_enabled_steps()
            pipeline_phases = self.config.get_enabled_phases()
            self.total_phases = len(pipeline_phases)
            
            if len(all_enabled_steps) == 0:
                self.log("WARNING", "No enabled steps found in configuration")
                return True
            
            # Setup progress bar with GUI
            self.progress_manager = ProgressBarManager(enable_gui=True)
            self.progress_manager.start()
            
            # Resume from specific phase if requested
            start_index = 0
            if resume_from:
                start_index = max(0, resume_from - 1)
                self.log("INFO", f"Resuming pipeline from phase {resume_from}")
            
            # Execute steps with proper phase numbering
            current_phase_number = 0
            
            for step_index, step in enumerate(all_enabled_steps):
                # Skip disabled steps
                if not step.get('Enabled', False):
                    self.log("INFO", f"Skipping disabled step: {step.get('Name', 'Unknown')}")
                    continue
                
                # Determine if this is a counter script
                is_counter = 'counter.py' in step.get('Path', '')
                
                # Increment phase number only for non-counter scripts
                if not is_counter:
                    current_phase_number += 1
                
                # Skip if we haven't reached the resume point
                if resume_from and current_phase_number < resume_from and not is_counter:
                    continue
                
                # Update overall progress
                if is_counter:
                    activity = f"Utility: {step.get('Name', 'Unknown')}"
                    percent_complete = int((current_phase_number / self.total_phases) * 100) if self.total_phases > 0 else 0
                else:
                    percent_complete = int((current_phase_number / self.total_phases) * 100)
                    activity = f"Phase {current_phase_number}: {step.get('Name', 'Unknown')}"
                    
                self.progress_manager.update_overall(percent_complete, activity)
                self.progress_manager.update_subtask(0, "Starting...")
                
                # Execute step
                success = self._execute_step(step, current_phase_number if not is_counter else 0)
                
                if not success:
                    if is_counter:
                        self.log("CRITICAL", f"Pipeline failed at utility: {step.get('Name', 'Unknown')}. Aborting.")
                    else:
                        self.log("CRITICAL", f"Pipeline failed at phase {current_phase_number}. Aborting.")
                    return False
            
            self.log("INFO", "Media Organizer pipeline completed successfully.")
            return True
            
        except KeyboardInterrupt:
            self.log("WARNING", "Pipeline interrupted by user")
            return False
        except Exception as e:
            self.log("CRITICAL", f"Unexpected error in pipeline: {e}")
            return False
        finally:
            if self.progress_manager:
                self.progress_manager.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Media Organizer Pipeline")
    parser.add_argument(
        '--config', 
        type=str, 
        help='Path to configuration file'
    )
    parser.add_argument(
        '--resume', 
        type=int, 
        metavar='PHASE', 
        help='Resume from specific phase number'
    )
    parser.add_argument(
        '--list-phases', 
        action='store_true', 
        help='List all pipeline phases and exit'
    )
    
    args = parser.parse_args()
    
    # Create orchestrator
    orchestrator = PipelineOrchestrator(args.config)
    
    # List phases if requested
    if args.list_phases:
        phases = orchestrator.config.get_pipeline_phases()
        print("Pipeline Phases:")
        for i, phase in enumerate(phases, 1):
            enabled = "[X]" if phase.get('Enabled', False) else "[ ]"
            print(f"  {i:2d}. {enabled} {phase.get('Name', 'Unknown')} ({phase.get('Type', 'Unknown')})")
        return 0
    
    # Run pipeline
    success = orchestrator.run(resume_from=args.resume)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())