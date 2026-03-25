import logging
from plugin import Plugin
from pyglui.pyfontstash import fontstash
from pyglui import ui
import threading
import pygame
from pyglui.cygl.utils import draw_polyline_norm, RGBA, draw_rounded_rect
import numpy as np

class HeadGesturePlugin(Plugin):
    """
    A minimal Pupil Core plugin template.
    """
    SURFACE_TOPIC = "surfaces"

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
        self.gaze_pos = [0.5, 0.5]
        self.ball_pos = [0.5, 0.5]
        self.gaze_lock = threading.Lock()
        self.my_param = 0.5
        
        self.game_state = False

        self.logger.info("HeadGesturePlugin initialized.")

    @classmethod
    def parse_pretty_class_name(cls):
        """Name shown in the plugin UI list"""
        return "Head Gestures"

    def init_ui(self):
        """Called when GUI is opened"""
        self.add_menu()
        self.menu.label = "Head Gesture Plugin Settings"
        self.menu.append(ui.Info_Text("This plugin demonstrates the head gestures."))
        
        self.menu.append(
            ui.Slider("my_param", self, min=0.0, max=1.0, step=0.05, label="My Parameter")
        )
        
        self.menu.append(
            ui.Button("Start Game Mode", self._init_pyglui_game_mode)
        )
        
        self.glfont = fontstash.Context()
        self.glfont.add_font("opensans", ui.get_opensans_font_path())
        
    def _init_pyglui_game_mode(self):
        """Starts game mode in a separate thread."""
        thread = threading.Thread(target=self._run_game_mode, daemon=True, name="HeadGestureGameMode")
        thread.start()
        
        self.game_state = True

    def _run_game_mode(self):
        """Pygame canvas window loop."""
        pygame.init()
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.display.set_caption("Head Gesture Game Mode")
        clock = pygame.time.Clock()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                    
                if running == False:    
                    with self.gaze_lock:
                        self.game_state = False

            screen.fill((255, 255, 255))  # White background

            # Draw a circle at the gaze position
            with self.gaze_lock:
                gaze_x = int(self.ball_pos[0] * screen.get_width())
                gaze_y = int(self.ball_pos[1] * screen.get_height())
                
            pygame.draw.circle(screen, (255, 0, 0), (gaze_x, gaze_y), 40)

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()
        

    def deinit_ui(self):
        """Called when GUI is closed or plugin stops"""
        self.remove_menu()
        
    def _get_gaze_positions(self, data):
        raw_gaze = data.get("gaze_on_surfaces", [])
        
        gaze_pos = []
        
        for gaze in raw_gaze:
            if gaze.get("on_surf", False):
                norm_pos = gaze.get("norm_pos", None)
                if norm_pos is not None:
                    gaze_pos.append(norm_pos)
            
        if len(gaze_pos) > 0:
            mean_pos = np.mean(gaze_pos, axis=0)
            return [mean_pos[1], 1 - mean_pos[0]]
        else:
            return [0.5, 0.5]
        

    def recent_events(self, events):
        if not self.game_state:
            return
        
        surface_gaze = events.get(self.SURFACE_TOPIC, [])
        if not surface_gaze:
            return
        
        gaze = self._get_gaze_positions(surface_gaze[0])
        with self.gaze_lock:
            self.gaze_pos = gaze

    def gl_display(self):
        pass
