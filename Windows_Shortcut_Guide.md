# How to Create a Taskbar Shortcut for a Python GUI

If you want another AI assistant or user to reproduce a one-click Taskbar shortcut for a Python program (`.py` file), you can show them these instructions!

### The Native Windows Method (Shortcut Creation)
1. **Right-click** on your Desktop environment or inside the folder.
2. Select **New -> Shortcut**.
3. In the location target, type out the path to the Python Windowed executable, followed by the path to the script:
   `pythonw.exe "C:\Users\brand\OneDrive - The University of Akron\CR Playground\Connecting MasterFlex Pump\pump_gui.py"`
   *(Note: Using `pythonw.exe` instead of `python.exe` ensures the black command prompt window remains cleanly hidden in the background, making it feel like a real native app).*
4. Click **Next**, name your shortcut "Masterflex Controller", and click **Finish**.
5. **Right-click** the newly created shortcut on your desktop, and click **Pin to taskbar**.

### Custom Application Icons
If you want to make it look even better on the taskbar, right-click the Shortcut you made, select **Properties**, click **Change Icon...**, and select any `.ico` file (or extract an icon from an existing `.exe`) before you pin it to the taskbar!
