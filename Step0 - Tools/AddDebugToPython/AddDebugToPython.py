import debugpy
import os; print(f"Python CWD: {os.getcwd()}")
# Define host and port (consider using environment variables for flexibility)
DEBUG_HOST = "localhost"
DEBUG_PORT = 5678

ENABLE_DEBUG = os.environ.get("ENABLE_PYTHON_DEBUG") == "1"
DEBUG_PORT = int(os.environ.get("PYTHON_DEBUG_PORT", 5678))

if ENABLE_DEBUG:
    try:
        print(f"--- Python Debugging Enabled ---", file=sys.stderr) # Use stderr for debug messages
        print(f"Attempting to listen on port {DEBUG_PORT}...", file=sys.stderr)
        debugpy.listen(("0.0.0.0", DEBUG_PORT))

        # Print the trigger for VS Code to Standard Output
        print(f"DEBUGPY_READY_ON:{DEBUG_PORT}")
        sys.stdout.flush() # Ensure it gets sent out

        print(f"--- Waiting for debugger attach on port {DEBUG_PORT}... ---", file=sys.stderr)
        debugpy.wait_for_client() # PAUSES HERE
        # **** Execution resumes AFTER debugger attaches ****
        print("--- wait_for_client() returned. Debugger supposedly attached. ---", file=sys.stderr)
        time.sleep(0.5) # Add a small delay to ensure debugger is fully settled
    except Exception as e:
        print(f"--- ERROR setting up debugpy on port {DEBUG_PORT}: {e} ---", file=sys.stderr)
        # exit(1) # Or just let the script continue