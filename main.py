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
from typing import Dict, List, Any, Optional, NamedTuple
import argparse
import re


class PipelineState(NamedTuple):
    """Holds all step counts and current positions for the pipeline."""
    number_of_steps: int
    number_of_real_steps: int
    number_of_enabled_steps: int
    number_of_enabled_real_steps: int
    current_step: int
    current_real_step: int
    current_enabled_step: int
    current_enabled_real_step: int

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from Utils.utils import get_config, MediaOrganizerConfig, setup_pipeline_logging, get_script_logger, create_logger_function, ProgressBarManager, show_progress_bar, stop_graphical_progress_bar


class PipelineOrchestrator:
    """
    Main pipeline orchestrator for the Media Organizer.
    Manages step execution, progress tracking, and error handling.
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
        self.current_step_index = 0
        self.total_real_steps = 0
        
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
    
    def _execute_python_script(self, script_path: str, step_name: str, current_state: PipelineState) -> bool:
        """
        Execute a Python script with progress tracking.

        Args:
            script_path: Path to the Python script
            step_name: Name of the step for logging
            current_state: Current pipeline state with all counters

        Returns:
            True if successful, False otherwise
        """
        try:
            # Prepare command - pass config object as JSON with progress info
            python_exe = sys.executable
            import json
            config_with_progress = self.config.config_data.copy()
            config_with_progress['_progress'] = current_state._asdict()
            config_json = json.dumps(config_with_progress, indent=None)
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
                # Update GUI to keep it responsive
                if self.progress_manager and self.progress_manager.enable_gui and self.progress_manager.form:
                    self.progress_manager.form.update()

                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break

                if output:
                    output = output.strip()
                    
                    # Check for progress updates
                    if output.startswith('PROGRESS:'):
                        try:
                            # Format: PROGRESS:overall_percent|Step X/Y: StepName - SubtaskMessage
                            parts = output[9:].split('|', 1)
                            if len(parts) == 2:
                                overall_percent = int(parts[0])
                                status_message = parts[1]

                                # Parse step info: "Step X/Y: StepName - SubtaskMessage"
                                if status_message.startswith('Step '):
                                    # Extract step numbers and details
                                    step_part, rest = status_message.split(':', 1)
                                    step_numbers = step_part.replace('Step ', '').strip()
                                    current_step, total_steps = map(int, step_numbers.split('/'))

                                    # Split step name and subtask message
                                    if ' - ' in rest:
                                        step_name, subtask_message = rest.split(' - ', 1)
                                        step_name = step_name.strip()
                                        subtask_message = subtask_message.strip()
                                    else:
                                        step_name = rest.strip()
                                        subtask_message = ""

                                    # Calculate subtask percent from overall percent
                                    step_weight = 100.0 / total_steps
                                    step_base = (current_step - 1) * step_weight
                                    subtask_percent = int(((overall_percent - step_base) / step_weight) * 100) if step_weight > 0 else 0
                                    subtask_percent = max(0, min(100, subtask_percent))

                                    # Update using the full progress method
                                    self.progress_manager.update_progress(
                                        total_steps, current_step, step_name, subtask_percent, subtask_message
                                    )
                                else:
                                    # Fallback: just update overall
                                    self.progress_manager.update_overall(overall_percent, status_message)
                        except (ValueError, IndexError) as e:
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
    
    def _execute_powershell_script(self, script_path: str, args: Dict[str, Any], step_name: str, current_state: PipelineState) -> bool:
        """
        Execute a PowerShell script (for backward compatibility during transition).

        Args:
            script_path: Path to the PowerShell script
            args: Arguments to pass to the script
            step_name: Name of the step for logging
            current_state: Current pipeline state with all counters

        Returns:
            True if successful, False otherwise
        """
        try:
            # Build PowerShell command
            cmd = ['pwsh', '-ExecutionPolicy', 'Bypass', '-File', script_path]

            # Add arguments (including state info)
            for key, value in args.items():
                cmd.extend([f'-{key}', str(value)])

            # Add pipeline state as separate arguments
            cmd.extend(['-NumberOfSteps', str(current_state.number_of_steps)])
            cmd.extend(['-NumberOfRealSteps', str(current_state.number_of_real_steps)])
            cmd.extend(['-NumberOfEnabledSteps', str(current_state.number_of_enabled_steps)])
            cmd.extend(['-NumberOfEnabledRealSteps', str(current_state.number_of_enabled_real_steps)])
            cmd.extend(['-CurrentStep', str(current_state.current_step)])
            cmd.extend(['-CurrentRealStep', str(current_state.current_real_step)])
            cmd.extend(['-CurrentEnabledStep', str(current_state.current_enabled_step)])
            cmd.extend(['-CurrentEnabledRealStep', str(current_state.current_enabled_real_step)])

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
    
    def _execute_step(self, step: Dict[str, Any], current_state: PipelineState) -> bool:
        """
        Execute a single pipeline step.

        Args:
            step: Step configuration dictionary
            current_state: Current pipeline state with all counters

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
        else:
            self.log("INFO", f"Starting Step {current_state.current_enabled_real_step}/{current_state.number_of_enabled_real_steps}: {step_name}")

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
            success = self._execute_python_script(str(script_path), step_name, current_state)
        elif step_type == 'PowerShell':
            script_path = PROJECT_ROOT / step_path
            args_dict = resolved_args if isinstance(resolved_args, dict) else {}
            success = self._execute_powershell_script(str(script_path), args_dict, step_name, current_state)
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
                self.log("INFO", f"Completed Step {current_state.current_enabled_real_step}/{current_state.number_of_enabled_real_steps}: {step_name}")
        else:
            if is_counter:
                self.log("ERROR", f"Failed utility: {step_name}")
            else:
                self.log("ERROR", f"Failed Step {current_state.current_enabled_real_step}/{current_state.number_of_enabled_real_steps}: {step_name}")
        
        return success
    
    def run(self, resume_from: Optional[int] = None) -> bool:
        """
        Run the entire pipeline.

        Args:
            resume_from: Optional step number to resume from

        Returns:
            True if pipeline completed successfully, False otherwise
        """
        try:
            # Setup logging
            self._setup_logging()
            
            # Validate environment
            if not self._validate_environment():
                return False
            
            # Calculate step counts using standard naming
            # Pattern: all_X = config.get_X(), number_of_X = len(all_X)

            all_steps = self.config.get_steps()  # All steps (enabled + disabled, including counters)
            number_of_steps = len(all_steps)

            all_real_steps = self.config.get_real_steps()  # All real steps (enabled + disabled, excluding counters)
            number_of_real_steps = len(all_real_steps)

            all_enabled_steps = self.config.get_enabled_steps()  # All enabled steps (including counters)
            number_of_enabled_steps = len(all_enabled_steps)

            all_enabled_real_steps = self.config.get_enabled_real_steps()  # Enabled real steps (excluding counters)
            number_of_enabled_real_steps = len(all_enabled_real_steps)

            if number_of_enabled_steps == 0:
                self.log("WARNING", "No enabled steps found in configuration")
                return True

            # Check if all enabled steps are interactive - if so, don't show progress bar
            all_interactive = all(step.get('Interactive', False) for step in all_enabled_steps)

            # Setup progress bar with GUI in main thread (prettier CustomTkinter GUI)
            # Don't show GUI if all steps are interactive
            enable_gui = not all_interactive
            self.progress_manager = ProgressBarManager(enable_gui=enable_gui, use_main_thread=True)
            self.progress_manager.start()

            # Resume from specific step if requested
            if resume_from:
                self.log("INFO", f"Resuming pipeline from step {resume_from}")

            # Initialize all current step counters
            current_real_step = 0  # Position in all_real_steps (all real steps including disabled, excluding counters)
            current_enabled_step = 0  # Position in all_enabled_steps (enabled steps including counters)
            current_enabled_real_step = 0  # Position in all_enabled_real_steps (enabled real steps - for progress bar)

            # Iterate through ALL steps (not just enabled) to track all counters accurately
            # enumerate gives us current_step starting at 0
            for current_step, step in enumerate(all_steps):

                # Determine if this is a counter script
                is_counter = 'counter.py' in step.get('Path', '')

                # Increment current_real_step for non-counter steps (all steps, enabled or not)
                if not is_counter:
                    current_real_step += 1

                # Check if step is enabled
                is_enabled = step.get('Enabled', False)

                # Skip disabled steps (don't execute, but we counted them)
                if not is_enabled:
                    continue

                # Increment current_enabled_step for enabled steps
                current_enabled_step += 1

                # Increment current_enabled_real_step for enabled real steps
                if not is_counter:
                    current_enabled_real_step += 1

                # Skip if we haven't reached the resume point
                if resume_from and current_enabled_real_step < resume_from and not is_counter:
                    continue

                # Create current state snapshot
                current_state = PipelineState(
                    number_of_steps=number_of_steps,
                    number_of_real_steps=number_of_real_steps,
                    number_of_enabled_steps=number_of_enabled_steps,
                    number_of_enabled_real_steps=number_of_enabled_real_steps,
                    current_step=current_step,
                    current_real_step=current_real_step,
                    current_enabled_step=current_enabled_step,
                    current_enabled_real_step=current_enabled_real_step
                )

                # Execute step with progress info
                # Note: Scripts receive all state info through config._progress
                success = self._execute_step(step, current_state)

                if not success:
                    if is_counter:
                        self.log("CRITICAL", f"Pipeline failed at utility: {step.get('Name', 'Unknown')}. Aborting.")
                    else:
                        self.log("CRITICAL", f"Pipeline failed at step {current_enabled_real_step}/{number_of_enabled_real_steps}. Aborting.")
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
        metavar='STEP',
        help='Resume from specific step number'
    )
    parser.add_argument(
        '--list-steps',
        action='store_true',
        help='List all pipeline steps and exit'
    )

    args = parser.parse_args()

    # Create orchestrator
    orchestrator = PipelineOrchestrator(args.config)

    # List steps if requested
    if args.list_steps:
        steps = orchestrator.config.get_enabled_real_steps()
        print("Pipeline Steps:")
        for i, step in enumerate(steps, 1):
            enabled = "[X]" if step.get('Enabled', False) else "[ ]"
            print(f"  {i:2d}. {enabled} {step.get('Name', 'Unknown')} ({step.get('Type', 'Unknown')})")
        return 0
    
    # Run pipeline
    success = orchestrator.run(resume_from=args.resume)
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())