import logging
from plugin import Plugin
from pyglui import ui

class MinimalPlugin(Plugin):
    """
    A minimal Pupil Core plugin template.
    """

    icon_chr = chr(0xEC08)  # Optional: icon for UI
    icon_font = "pupil_icons"  # Font for the icon

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Setup logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.hasHandlers():
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            self.logger.addHandler(handler)

        # Example variable
        self.my_param = 0.5

        self.logger.info("MinimalPlugin initialized.")

    @classmethod
    def parse_pretty_class_name(cls):
        """Name shown in the plugin UI list"""
        return "Minimal Plugin"

    def init_ui(self):
        """Called when GUI is opened"""
        self.add_menu()
        self.menu.label = "Minimal Plugin Settings"
        self.menu.append(ui.Info_Text("This is a minimal plugin."))
        self.menu.append(ui.Slider("my_param", self, min=0.0, max=1.0, step=0.05, label="My Parameter"))

    def deinit_ui(self):
        """Called when GUI is closed or plugin stops"""
        self.remove_menu()

    def recent_events(self, events):
        """Main logic that runs every frame"""
        self.logger.debug("Processing frame...")

    def gl_display(self):
        """Draw something in the OpenGL view if needed"""
        pass
