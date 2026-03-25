import logging
from plugin import Plugin
from pyglui import ui
from pyglui.cygl.utils import RGBA, draw_rounded_rect
from pyglui.pyfontstash import fontstash
import numpy as np


class SaccadeGestureDetector(Plugin):
    CUSTOM_TOPIC = "saccade_gestures"
    TRIGGER_TOPIC = "objects"
    LEGEND_TEXT = "Saccade Gestures"

    icon_chr = chr(0xEC12)
    icon_font = "pupil_icons"

    def __init__(self, *args, **kwargs):
        """
        Initialize the detector with origin position, timestamp, and distance thresholds.

        :param origin_pos: The origin position (x, y) for the saccade gesture.
        :param start_timestamp: The timestamp when the gesture detection started.
        :param dist_max: Maximum distance from the origin for detecting a saccade.
        :param dist_min: Minimum distance to consider the gaze returned.
        """
        super().__init__(*args, **kwargs)

        # Initialize logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.hasHandlers():
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        self.dist_max = 0.3
        self.dist_min = 0.1
        self.max_gesture_duration = 0.5

        # Visualization variables
        self.info_text_color = (0.0, 0.0, 0.0, 1.0)  # Black Text
        self.info_text_bg = RGBA(0.8, 0.8, 1.0, 1.0)

        self.start_timestamp = None
        self.origin_pos = None

        self.gaze_point_buffer = []
        self.direction = None
        self.gaze_outside_origin = False
        self.finished = False

        self.trigger_event = None
        self.last_trigger_id = None
        self.curr_object = None
        self.viz_text = ""

        self.logger.info("SaccadeGestureDetector initialized.")

    @classmethod
    def parse_pretty_class_name(cls):
        return "Saccade Gesture Detector"

    def init_ui(self):
        self.add_menu()
        self.menu.label = "Saccade Gesture Detector Settings"
        self.menu.append(
            ui.Info_Text(
                "This plugin detects saccade gestures based on gaze movements relative to a fixation point."
            )
        )
        self.menu.append(
            ui.Slider(
                "dist_max",
                self,
                min=0.01,
                step=0.01,
                max=1,
                label="Origin Radius"
            )
        )
        self.menu.append(
            ui.Slider(
                "dist_min",
                self,
                min=0.01,
                step=0.01,
                max=0.2,
                label="Return Threshold"
            )
        )
        self.menu.append(
            ui.Slider(
                "max_gesture_duration",
                self, min=0.01,
                step=0.01,
                max=2.0,
                label="Gesture Max Duration"
            )
        )

        # Initialize font context for text rendering
        self.glfont = fontstash.Context()
        self.glfont.add_font("opensans", ui.get_opensans_font_path())
        self.glfont.set_size(20)
        self.glfont.set_color_float((0.0, 0.0, 0.0, 1.0))  # Black text

    def gl_display(self):
        # Position where the text will be drawn
        x_legend, y_legend = 20, 670

        # Draw the rounded rectangle
        draw_rounded_rect(
            (x_legend - 10, y_legend - 17),
            (x_legend + (8 * len(self.LEGEND_TEXT)), 23),
            corner_radius=5.0,
            color=self.info_text_bg
        )
        self.glfont.draw_text(x_legend, y_legend, self.LEGEND_TEXT)

        if self.viz_text:
            # Position where the text will be drawn
            x, y = 20, 140

            # Draw the rounded rectangle
            draw_rounded_rect(
                (x - 10, y - 17),
                (x + (8 * len(self.viz_text)), 23),
                corner_radius=5.0,
                color=self.info_text_bg
            )
            self.glfont.draw_text(x, y, self.viz_text)

    def deinit_ui(self):
        self.remove_menu()
        self.glfont = None

    def _check_origin_max_distance(self, gaze_point):
        """
        Check if the gaze point is within the maximum distance from the origin.
        """
        o_dist = np.linalg.norm(np.array(gaze_point) - self.origin_pos)
        return o_dist > self.dist_max

    def _check_origin_min_distance(self, gaze_point):
        """
        Check if the gaze point is outside the minimum distance from the origin.
        """
        o_dist = np.linalg.norm(np.array(gaze_point) - self.origin_pos)
        return o_dist < self.dist_min

    def _publish_event(self, events):
        """Publish a custom event when a gesture is detected."""
        custom_datum = {
            "topic": self.CUSTOM_TOPIC,
            "timestamp": self.g_pool.get_timestamp(),
            "object": self.trigger_event["object"],
            "direction": self.direction,
        }
        events.setdefault(self.CUSTOM_TOPIC, []).append(custom_datum)

    def recent_events(self, events):
        self.logger.debug(self.TRIGGER_TOPIC in events and self.trigger_event is None)

        if self.TRIGGER_TOPIC in events and self.trigger_event is None:
            self.trigger_event = events[self.TRIGGER_TOPIC][-1]

            self.last_trigger_id = self.trigger_event.get('id', None)
            self.curr_object = self.trigger_event.get('object', None)

            self.start_timestamp = self.g_pool.get_timestamp()
            self.origin_pos = np.array(self.trigger_event["norm_pos"])

            self.logger.info('Starting Saccade Gesture Detection')

        if self.trigger_event is not None:
            gaze_data = events.get("gaze", [])

            for gaze in gaze_data:
                gaze_point = gaze["norm_pos"]
                current_time = self.g_pool.get_timestamp()

                if self.finished:
                    break

                if self._check_origin_max_distance(gaze_point):
                    self.gaze_point_buffer.append(gaze_point)

                if not self.gaze_outside_origin:
                    if self._check_origin_max_distance(gaze_point):
                        self.gaze_outside_origin = True
                        self.start_timestamp = self.g_pool.get_timestamp()
                else:
                    if current_time - self.start_timestamp >= self.max_gesture_duration:
                        self.finished = True
                        self.direction = None
                        self.logger.debug("Gesture detection Interupted.")
                        break

                    if self._check_origin_min_distance(gaze_point):
                        mean_point = np.mean(self.gaze_point_buffer, axis=0)

                        delta = np.array(mean_point) - np.array(self.origin_pos)
                        angle = np.degrees(np.arctan2(delta[1], delta[0])) % 360

                        if 45 <= angle < 135:
                            self.direction = 'up'
                        elif 135 <= angle < 225:
                            self.direction = 'left'
                        elif 225 <= angle < 315:
                            self.direction = 'down'
                        else:
                            self.direction = 'right'

                        self.finished = True

            if self.finished:
                self._set_viz_text()

                if self.direction:
                    self._publish_event(events)
                    self.logger.debug(f"Saccade detected: {self.direction} on {self.trigger_event['object']}")

                self._reset_state()

    def _set_viz_text(self):
        """Set the visualization text to display the detected gesture."""
        if all([self.last_trigger_id, self.direction, self.curr_object]):
            self.viz_text = (
                f"{self.last_trigger_id} - {self.direction.upper()} on {self.curr_object.upper()}"
            )

    def _reset_state(self):
        """Reset all state variables for the detector."""
        self.trigger_event = None
        self.finished = False
        self.origin_pos = None
        self.start_timestamp = None
        self.gaze_outside_origin = False
        self.gaze_point_buffer = []
