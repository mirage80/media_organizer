"""
Minimal utilities module for Media Organizer pipeline.
All configuration values are loaded from config.json.
"""

import os
import sys
import json
import logging
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

logger = logging.getLogger(__name__)

# =============================================================================
# LOAD CONFIG.JSON
# =============================================================================

def _load_config():
    """Load config.json file."""
    config_path = Path(__file__).parent / "config.json"
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_config = _load_config()
_style = _config.get('settings', {}).get('gui', {}).get('style', {})


# =============================================================================
# GUI STYLE - Values from config.json
# =============================================================================

class GUIStyle:
    """GUI styling constants loaded from config.json."""

    _fc = _style.get('frameColors', {})
    _pc = _style.get('progressColors', {})
    _tc = _style.get('textColors', {})
    _dim = _style.get('dimensions', {})
    _fonts = _style.get('fonts', {})
    _grid = _style.get('thumbnailGrid', {})
    _thumb = _style.get('thumbnail', {})

    # Colors
    FRAME_BG_PRIMARY = _fc.get('primary', "#e8f5e9")
    FRAME_BG_SECONDARY = _fc.get('secondary', "#fff3e0")
    PROGRESS_COLOR_PRIMARY = _pc.get('primaryBar', "#4CAF50")
    PROGRESS_BG_PRIMARY = _pc.get('primaryBackground', "#C8E6C9")
    PROGRESS_COLOR_SECONDARY = _pc.get('secondaryBar', "#FF9800")
    PROGRESS_BG_SECONDARY = _pc.get('secondaryBackground', "#FFE0B2")
    TEXT_COLOR_PRIMARY = _tc.get('primary', "#2e7d32")
    TEXT_COLOR_SECONDARY = _tc.get('secondary', "#e65100")

    # Dimensions
    CORNER_RADIUS = _dim.get('cornerRadius', 8)
    CORNER_RADIUS_LARGE = _dim.get('cornerRadiusLarge', 15)
    PADDING_OUTER = _dim.get('paddingOuter', 10)
    PADDING_INNER = _dim.get('paddingInner', 5)
    PADDING_CONTENT = _dim.get('paddingContent', 15)
    PADDING_WIDGET = _dim.get('paddingWidget', 5)
    PROGRESS_HEIGHT = _dim.get('progressBarHeight', 20)

    # Fonts
    FONT_FAMILY = _fonts.get('family', "Segoe UI")
    FONT_SIZE_HEADING = _fonts.get('sizeHeading', 14)
    FONT_SIZE_NORMAL = _fonts.get('sizeNormal', 11)

    # Grid
    GRID_MIN_THUMBNAIL_SIZE = _grid.get('minSize', 200)
    GRID_MAX_THUMBNAIL_SIZE = _grid.get('maxSize', 300)
    GRID_DEFAULT_COLUMNS = _grid.get('defaultColumns', 4)
    GRID_POPUP_SCREEN_FRACTION = _grid.get('popupScreenFraction', 0.33)
    GRID_HOVER_DELAY_MS = _grid.get('hoverDelayMs', 500)
    GRID_CARD_PADDING = _grid.get('cardPadding', 40)
    GRID_CARD_BORDER_PADDING = _grid.get('cardBorderPadding', 2)
    GRID_SCREEN_DIVISOR = 7
    GRID_SCROLLBAR_WIDTH = 20
    GRID_MIN_USABLE_WIDTH = 100
    GRID_SCREEN_BORDER = 20
    GRID_TITLEBAR_HEIGHT = 40
    GRID_FRAME_SEPARATOR = 10

    # Thumbnail
    THUMBNAIL_WIDTH = _thumb.get('width', 200)
    THUMBNAIL_HEIGHT = _thumb.get('height', 200)
    THUMBNAIL_QUALITY = _thumb.get('quality', 85)

    # Window frame
    WINDOW_FRAME_CORNER_RADIUS = 0
    WINDOW_FRAME_BORDER_WIDTH = 0
    WINDOW_FRAME_PADX = PADDING_OUTER
    WINDOW_FRAME_PADY_TOP = PADDING_OUTER
    WINDOW_FRAME_PADY_BOTTOM_TOP = PADDING_INNER
    WINDOW_FRAME_PADY_BOTTOM_BOTTOM = PADDING_OUTER

    @staticmethod
    def create_styled_frame(parent, use_ctk=True, secondary=False, corner_radius=None, border_width=0):
        """Create a styled frame."""
        bg = GUIStyle.FRAME_BG_SECONDARY if secondary else GUIStyle.FRAME_BG_PRIMARY
        cr = corner_radius if corner_radius is not None else GUIStyle.CORNER_RADIUS
        if use_ctk:
            try:
                from customtkinter import CTkFrame
                return CTkFrame(parent, fg_color=bg, corner_radius=cr, border_width=border_width)
            except ImportError:
                pass
        import tkinter as tk
        return tk.Frame(parent, bg=bg, relief="solid" if border_width else "flat", borderwidth=border_width)


# =============================================================================
# CONFIG MANAGER
# =============================================================================

class MediaOrganizerConfig:
    """Configuration manager - loads from config.json."""

    def __init__(self, config_file: Optional[str] = None):
        if config_file is None:
            config_file = Path(__file__).parent / "config.json"
        self.config_file = Path(config_file)
        
        # Load config with proper error handling
        try:
            if not self.config_file.exists():
                raise FileNotFoundError(f"Config file not found: {self.config_file}")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Configuration error: {e}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file {self.config_file}: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to load config file {self.config_file}: {e}") from e
        
        self.resolved_paths = {}
        for key in ['rawDirectory', 'processedDirectory', 'logDirectory', 'resultsDirectory']:
            if key in self.config_data.get('paths', {}):
                self.resolved_paths[key] = self.config_data['paths'][key]

    def get_settings(self) -> Dict[str, Any]:
        return self.config_data.get('settings', {})

    def get_paths(self) -> Dict[str, str]:
        return self.resolved_paths.copy()

    def get_pipeline_steps(self) -> List[Dict[str, Any]]:
        return self.config_data.get('pipelineSteps', [])

    def get_steps(self) -> List[Dict[str, Any]]:
        """Get all pipeline steps (enabled and disabled)."""
        return self.get_pipeline_steps()

    def get_real_steps(self) -> List[Dict[str, Any]]:
        """Get all real steps (excluding counters)."""
        return [s for s in self.get_pipeline_steps() if 'counter.py' not in s.get('Path', '')]

    def get_enabled_steps(self) -> List[Dict[str, Any]]:
        """Get all enabled steps (including counters)."""
        return [s for s in self.get_pipeline_steps() if s.get('Enabled', False)]

    def get_enabled_real_steps(self) -> List[Dict[str, Any]]:
        """Get enabled real steps (excluding counters)."""
        return [s for s in self.get_pipeline_steps()
                if s.get('Enabled', False) and 'counter.py' not in s.get('Path', '')]

    def validate_tools(self) -> List[str]:
        """Validate required tools are available. Returns list of missing tools."""
        import shutil
        missing = []
        tools = self.config_data.get('paths', {}).get('tools', {})
        for name, cmd in tools.items():
            if not shutil.which(cmd):
                missing.append(f"{name} ({cmd})")
        return missing

    def ensure_directories(self) -> None:
        """Ensure all required directories exist."""
        for key in ['rawDirectory', 'processedDirectory', 'logDirectory', 'resultsDirectory']:
            path = self.resolved_paths.get(key)
            if path:
                Path(path).mkdir(parents=True, exist_ok=True)

    def setup_environment_variables(self) -> None:
        """Setup environment variables for pipeline."""
        os.environ['MEDIA_ORGANIZER_CONFIG'] = str(self.config_file)

    def resolve_step_arguments(self, args: Any) -> Dict[str, Any]:
        """Resolve step arguments with path variables."""
        if isinstance(args, dict):
            resolved = {}
            for k, v in args.items():
                if isinstance(v, str) and v.startswith('$'):
                    var_name = v[1:]
                    resolved[k] = self.resolved_paths.get(var_name, v)
                else:
                    resolved[k] = v
            return resolved
        return {}


_config_instance = None

def get_config(config_file: Optional[str] = None) -> MediaOrganizerConfig:
    """Get global config instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = MediaOrganizerConfig(config_file)
    return _config_instance


# =============================================================================
# FILE UTILITIES
# =============================================================================

class FileUtils:
    """File operation utilities."""

    @staticmethod
    def atomic_write_json(data: Any, file_path: Union[str, Path], indent: int = 2) -> bool:
        """Atomically write JSON to file."""
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=file_path.parent,
                                              suffix='.tmp', encoding='utf-8') as tmp:
                json.dump(data, tmp, indent=indent, ensure_ascii=False)
                temp_path = tmp.name
            Path(temp_path).replace(file_path)
            return True
        except Exception as e:
            logger.error(f"Atomic write failed for {file_path}: {e}")
            return False


class PathUtils:
    """Path utilities."""

    @staticmethod
    def normalize_path(path: Union[str, Path]) -> str:
        """
        Normalize path to POSIX format (forward slashes).
        
        Note: Always returns forward slashes, not Windows backslashes.
        Use Path.resolve() for OS-specific normalization instead.
        """
        return str(Path(path).as_posix()) if path else str(path)

    @staticmethod
    def ensure_directory(directory: Union[str, Path]) -> bool:
        try:
            Path(directory).mkdir(parents=True, exist_ok=True)
            return True
        except Exception:
            return False


# =============================================================================
# LOGGING
# =============================================================================

class MediaOrganizerLogger:
    """Logger for pipeline scripts."""

    def __init__(self, log_directory: str, script_name: str, step: str = "0"):
        self.log_directory = Path(log_directory)
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self.log_file_path = self.log_directory / f"Step_{step}_{script_name}.log" if step else self.log_directory / f"{script_name}.log"
        self._lock = threading.Lock()
        self.logger = self._setup_logger(script_name, step)

    def _setup_logger(self, script_name, step):
        if self.log_file_path.exists():
            try:
                self.log_file_path.unlink()
            except:
                pass

        log = logging.getLogger(f"media_organizer.{script_name}.{step}")
        log.setLevel(logging.DEBUG)
        for h in log.handlers[:]:
            h.close()
            log.removeHandler(h)

        fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S')

        try:
            fh = logging.FileHandler(self.log_file_path, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except:
            pass

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        log.addHandler(ch)
        log.propagate = False
        return log

    def debug(self, msg):
        with self._lock: self.logger.debug(msg)
    def info(self, msg):
        with self._lock: self.logger.info(msg)
    def warning(self, msg):
        with self._lock: self.logger.warning(msg)
    def error(self, msg):
        with self._lock: self.logger.error(msg)


def get_script_logger(log_directory: str, script_name: str, step: str = "0") -> MediaOrganizerLogger:
    """Get a logger for a script."""
    return MediaOrganizerLogger(log_directory, script_name, step)

def get_script_logger_with_config(config_data: dict, script_name: str) -> MediaOrganizerLogger:
    """Get logger using config data."""
    log_dir = config_data['paths']['logDirectory']
    step = str(config_data.get('_progress', {}).get('current_step', 0))
    return get_script_logger(log_dir, script_name, step)

def setup_pipeline_logging(log_directory: str) -> None:
    """Setup global pipeline logging."""
    Path(log_directory).mkdir(parents=True, exist_ok=True)

def create_logger_function(logger_instance: MediaOrganizerLogger):
    """Create a log function from logger instance."""
    def log_fn(level: str, message: str):
        getattr(logger_instance, level.lower(), logger_instance.info)(message)
    return log_fn


# =============================================================================
# PROGRESS BAR
# =============================================================================

_global_progress_manager = None

try:
    import tkinter as tk
    from tkinter import ttk
    import queue
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False


class ProgressBarManager:
    """Progress bar manager with GUI support."""

    def __init__(self, enable_gui: bool = True, use_main_thread: bool = False):
        self.enable_gui = enable_gui and GUI_AVAILABLE
        self.use_main_thread = use_main_thread
        self.root = self.form = self.overall_bar = self.step_bar = None
        self.step_label = self.subtask_label = None
        self.command_queue = queue.Queue() if GUI_AVAILABLE else None
        self.gui_thread = None
        self.running = False

    def start(self):
        global _global_progress_manager
        _global_progress_manager = self
        self.running = True
        if self.enable_gui:
            if self.use_main_thread:
                self._create_progress_form()
            else:
                self.gui_thread = threading.Thread(target=self._gui_worker, daemon=True)
                self.gui_thread.start()

    def stop(self):
        self.running = False
        if self.enable_gui and self.gui_thread:
            self._send_command('stop')
            self.gui_thread.join(timeout=2.0)

    def update_overall(self, percent: int, activity: str):
        if self.enable_gui:
            self._send_command('update_overall', percent=percent, activity=activity)
        else:
            print(f"Progress: {percent}% - {activity}")

    def update_subtask(self, percent: int, message: str):
        if self.enable_gui:
            self._send_command('update_subtask', percent=percent, message=message)

    def update_progress(self, total_steps: int, current_step: int, step_name: str,
                       subtask_percent: int, subtask_message: str = ""):
        weight = 100.0 / total_steps if total_steps > 0 else 100.0
        overall = (current_step - 1) * weight + weight * subtask_percent / 100.0
        label = f"Step {current_step}/{total_steps}: {step_name}"

        if self.enable_gui:
            if self.use_main_thread:
                self._update_direct(int(overall), label, subtask_percent, subtask_message)
            else:
                self._send_command('update_overall', percent=int(overall), activity=label)
                self._send_command('update_subtask', percent=subtask_percent, message=subtask_message)
        else:
            print(f"Progress: {overall:.1f}% - {label}")

    def send_to_back(self):
        if self.enable_gui:
            if self.use_main_thread and self.form:
                try:
                    self.form.withdraw()
                except:
                    pass
            else:
                self._send_command('send_to_back')

    def bring_to_front(self):
        if self.enable_gui:
            if self.use_main_thread and self.form:
                try:
                    self.form.deiconify()
                    self.form.lift()
                except:
                    pass
            else:
                self._send_command('bring_to_front')

    def hide(self):
        """Hide the progress bar window completely."""
        if self.enable_gui and self.form:
            try:
                self.form.withdraw()
            except:
                pass

    def show(self):
        """Show the progress bar window."""
        if self.enable_gui and self.form:
            try:
                self.form.deiconify()
                self.form.lift()
                self.form.focus_force()
            except:
                pass

    def _send_command(self, cmd, **kwargs):
        if self.command_queue:
            self.command_queue.put((cmd, kwargs))

    def _update_direct(self, overall, label, subtask, msg):
        if self.overall_bar:
            if hasattr(self.overall_bar, 'set'):
                self.overall_bar.set(overall / 100.0)
            else:
                self.overall_bar['value'] = overall
        if self.step_label:
            self.step_label.configure(text=label)
        if self.step_bar:
            if hasattr(self.step_bar, 'set'):
                self.step_bar.set(subtask / 100.0)
            else:
                self.step_bar['value'] = subtask
        if self.subtask_label:
            self.subtask_label.configure(text=msg)

    def _gui_worker(self):
        try:
            try:
                from customtkinter import CTk
                self.root = None
            except ImportError:
                self.root = tk.Tk()
                self.root.withdraw()

            self._create_progress_form()
            target = self.root or self.form
            target.after(50, self._process_commands)
            target.mainloop()
        except Exception as e:
            logger.error(f"GUI worker error: {e}")
        finally:
            self._cleanup()

    def _create_progress_form(self):
        try:
            from customtkinter import CTk, CTkFrame, CTkProgressBar, CTkLabel, set_appearance_mode
            use_ctk = True
        except ImportError:
            use_ctk = False

        if use_ctk:
            temp = CTk()
            temp.withdraw()
            temp.update_idletasks()
            sw, sh = temp.winfo_screenwidth(), temp.winfo_screenheight()
            temp.destroy()

            self.form = CTk()
            self.form.title("Media Organizer Progress")
            self.form.geometry(f"{sw//4}x{sh//5}")
            set_appearance_mode("system")

            top = CTkFrame(self.form, fg_color=GUIStyle.FRAME_BG_PRIMARY, corner_radius=GUIStyle.CORNER_RADIUS)
            top.pack(fill="both", expand=True, padx=10, pady=(10, 5))

            CTkLabel(top, text="Overall Progress", font=(GUIStyle.FONT_FAMILY, 14, "bold"),
                    text_color=GUIStyle.TEXT_COLOR_PRIMARY).pack(pady=(10, 5), padx=15, anchor="w")

            self.overall_bar = CTkProgressBar(top, progress_color=GUIStyle.PROGRESS_COLOR_PRIMARY,
                                             fg_color=GUIStyle.PROGRESS_BG_PRIMARY, height=20)
            self.overall_bar.set(0)
            self.overall_bar.pack(fill="x", padx=15, pady=5)

            self.step_label = CTkLabel(top, text="Not started", font=(GUIStyle.FONT_FAMILY, 11),
                                      text_color=GUIStyle.TEXT_COLOR_PRIMARY, anchor="w")
            self.step_label.pack(fill="x", padx=15, pady=(5, 10))

            bot = CTkFrame(self.form, fg_color=GUIStyle.FRAME_BG_SECONDARY, corner_radius=GUIStyle.CORNER_RADIUS)
            bot.pack(fill="both", expand=True, padx=10, pady=(5, 10))

            CTkLabel(bot, text="Current Task", font=(GUIStyle.FONT_FAMILY, 14, "bold"),
                    text_color=GUIStyle.TEXT_COLOR_SECONDARY).pack(pady=(10, 5), padx=15, anchor="w")

            self.step_bar = CTkProgressBar(bot, progress_color=GUIStyle.PROGRESS_COLOR_SECONDARY,
                                          fg_color=GUIStyle.PROGRESS_BG_SECONDARY, height=20)
            self.step_bar.set(0)
            self.step_bar.pack(fill="x", padx=15, pady=5)

            self.subtask_label = CTkLabel(bot, text="Not started", font=(GUIStyle.FONT_FAMILY, 11),
                                         text_color=GUIStyle.TEXT_COLOR_SECONDARY, anchor="w")
            self.subtask_label.pack(fill="x", padx=15, pady=(5, 10))
        else:
            if self.root is None:
                self.root = tk.Tk()
                self.root.withdraw()
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            self.form = tk.Toplevel(self.root)
            self.form.title("Media Organizer Progress")
            self.form.geometry(f"{sw//4}x{sh//5}")

            self.overall_bar = ttk.Progressbar(self.form, maximum=100)
            self.overall_bar.pack(fill="x", padx=15, pady=(20, 5))
            self.step_label = tk.Label(self.form, text="Not started", anchor="w")
            self.step_label.pack(fill="x", padx=15, pady=5)
            self.step_bar = ttk.Progressbar(self.form, maximum=100)
            self.step_bar.pack(fill="x", padx=15, pady=5)
            self.subtask_label = tk.Label(self.form, text="Not started", anchor="w")
            self.subtask_label.pack(fill="x", padx=15, pady=(5, 20))

        self.form.resizable(False, False)
        self.form.protocol("WM_DELETE_WINDOW", lambda: None)
        try:
            self.form.attributes("-topmost", True)
        except:
            pass

        self.form.update_idletasks()
        w, h = self.form.winfo_width(), self.form.winfo_height()
        x = (self.form.winfo_screenwidth() - w) // 2
        y = (self.form.winfo_screenheight() - h) // 2
        self.form.geometry(f"{w}x{h}+{x}+{y}")
        self.form.deiconify()

    def _process_commands(self):
        try:
            while not self.command_queue.empty():
                cmd, kw = self.command_queue.get_nowait()
                if cmd == 'stop':
                    self._cleanup()
                    if self.root:
                        self.root.quit()
                    return
                elif cmd == 'update_overall':
                    if self.overall_bar:
                        p = max(0, min(100, kw.get('percent', 0)))
                        if hasattr(self.overall_bar, 'set'):
                            self.overall_bar.set(p / 100.0)
                        else:
                            self.overall_bar['value'] = p
                    if self.step_label:
                        self.step_label.configure(text=kw.get('activity', ''))
                elif cmd == 'update_subtask':
                    if self.step_bar:
                        p = max(0, min(100, kw.get('percent', 0)))
                        if hasattr(self.step_bar, 'set'):
                            self.step_bar.set(p / 100.0)
                        else:
                            self.step_bar['value'] = p
                    if self.subtask_label:
                        self.subtask_label.configure(text=kw.get('message', ''))
                elif cmd == 'send_to_back' and self.form:
                    self.form.withdraw()
                elif cmd == 'bring_to_front' and self.form:
                    self.form.deiconify()
                    self.form.lift()
        except:
            pass

        if self.running:
            (self.root or self.form).after(50, self._process_commands)

    def _cleanup(self):
        try:
            if self.form:
                self.form.destroy()
            if self.root:
                self.root.destroy()
        except:
            pass
        self.form = self.root = None


def update_pipeline_progress(total_steps: int, current_step: int, step_name: str,
                            subtask_percent: int, subtask_message: str = ""):
    """Update progress bar from any script."""
    weight = 100.0 / total_steps if total_steps > 0 else 100.0
    overall = (current_step - 1) * weight + weight * subtask_percent / 100.0
    print(f"PROGRESS:{int(overall)}|Step {current_step}/{total_steps}: {step_name} - {subtask_message}", flush=True)

    if _global_progress_manager:
        try:
            _global_progress_manager.update_progress(total_steps, current_step, step_name,
                                                     subtask_percent, subtask_message)
        except:
            pass


# Legacy compatibility
def show_progress_bar(iteration, total, prefix='', suffix='', **kw):
    if total > 0:
        pct = min(int(iteration / total * 100), 100)
        print(f"\r{prefix} [{'=' * (pct // 2):<50}] {pct}% {suffix}", end="\r", flush=True)

def stop_graphical_progress_bar(logger=None):
    print("\nProgress complete.", flush=True)

def write_json_atomic(data, path, logger=None):
    return FileUtils.atomic_write_json(data, path)
