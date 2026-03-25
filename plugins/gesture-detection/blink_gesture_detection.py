import logging
from collections import deque
from plugin import Plugin
from pyglui import ui
from pyglui.cygl.utils import RGBA, draw_rounded_rect
from pyglui.pyfontstash import fontstash

class BlinkObjectDetector(Plugin):
    CUSTOM_TOPIC = "blink_gestures"
    TRIGGER_TOPIC = "objects"
    LEGEND_TEXT = "Blink Gestures"

    icon_chr = chr(0xEC08)
    icon_font = "pupil_icons"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Logger setup
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        if not self.logger.hasHandlers():
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        # Blink detection parameters
        self.confidence_onset_threshold = 0.5  # Confidence drop threshold for onset
        self.confidence_offset_threshold = 0.8  # Confidence recovery threshold for offset
        self.history_length = 0.3  # Time window to track confidence (seconds)
        self.object_association_time = 1.0  # Association time window (seconds)

        # State variables
        self.blink_timestamps = deque()  # Stores detected blink events
        self.pupil_history = deque()  # Tracks pupil data for confidence analysis
        self.current_object = None
        self.current_object_time = None
        self.last_trigger_id = None

        # Visualization
        self.glfont = None
        self.viz_text = ""
        self.info_text_color = (0.0, 0.0, 0.0, 1.0)  # Black Text
        self.info_text_bg = RGBA(1.0, 1.0, 0.8, 1.0)

        self.logger.info("BlinkObjectDetector initialized.")

    @classmethod
    def parse_pretty_class_name(cls) -> str:
        return "Blink Object Detector"

    def init_ui(self):
        self.add_menu()
        self.menu.label = "Blink Object Detection Parameters"
        self.menu.append(ui.Info_Text("This plugin detects blinks and associates them with objects."))
        self.menu.append(
            ui.Slider(
                "confidence_onset_threshold",
                self,
                min=0.1,
                max=1.0,
                step=0.05,
                label="Blink Onset Confidence Threshold"
            )
        )
        self.menu.append(
            ui.Slider(
                "confidence_offset_threshold",
                self,
                min=0.1,
                max=1.0,
                step=0.05,
                label="Blink Offset Confidence Threshold"
            )
        )
        self.menu.append(
            ui.Slider(
                "object_association_time",
                self,
                min=0.1,
                max=5.0,
                step=0.1,
                label="Object Association Time"
            )
        )

        # Initialize font context for visualization
        self.glfont = fontstash.Context()
        self.glfont.add_font("opensans", ui.get_opensans_font_path())
        self.glfont.set_size(20)
        self.glfont.set_color_float((0.0, 0.0, 0.0, 1.0))  # Black text

    def deinit_ui(self):
        self.remove_menu()
        self.glfont = None

    def recent_events(self, events):
        """Process incoming events to detect blinks and associate them with objects."""
        pupil_data = events.get("pupil", [])
        object_events = events.get(self.TRIGGER_TOPIC, [])

        current_time = self.g_pool.get_timestamp()

        # Update pupil history
        for pupil in pupil_data:
            self.pupil_history.append(pupil)
            while self.pupil_history and current_time - self.pupil_history[0]["timestamp"] > self.history_length:
                self.pupil_history.popleft()

        # Detect blinks
        self._detect_blinks()

        # Associate blinks with objects
        for blink in self.blink_timestamps:
            if "associated" not in blink:
                self._associate_blink_with_object(blink, object_events, events)

        # Reset object association if time expires
        if self.current_object and self.current_object_time:
            if current_time - self.current_object_time > self.object_association_time:
                self._reset_object()

    def _detect_blinks(self):
        """Detect discrete blinks based on pupil confidence values."""
        blink_in_progress = False  # Track whether a blink is ongoing

        for pupil in self.pupil_history:
            confidence = pupil.get("confidence", 0)
            timestamp = pupil["timestamp"]

            if not blink_in_progress and confidence <= self.confidence_onset_threshold:
                # Blink onset detected
                self.logger.debug(f"Blink onset detected at {timestamp}")
                self.blink_timestamps.append({"type": "onset", "timestamp": timestamp})
                blink_in_progress = True  # Blink started

            elif blink_in_progress and confidence >= self.confidence_offset_threshold:
                # Blink offset detected
                self.logger.debug(f"Blink offset detected at {timestamp}")
                self.blink_timestamps.append({"type": "offset", "timestamp": timestamp})
                blink_in_progress = False  # Blink ended

        # Filter and consolidate blink timestamps (only paired onsets and offsets)
        self.blink_timestamps = [
            blink for blink in self.blink_timestamps if
            self.g_pool.get_timestamp() - blink["timestamp"] <= self.history_length
        ]

        # Count discrete blinks
        self.discrete_blink_count = sum(1 for blink in self.blink_timestamps if blink["type"] == "onset")

    def _associate_blink_with_object(self, blink, object_events, events):
        """Associate a detected blink with an object."""
        closest_object = min(
            object_events,
            key=lambda obj_event: abs(obj_event["timestamp"] - blink["timestamp"]),
            default=None,
        )

        if closest_object and abs(closest_object["timestamp"] - blink["timestamp"]) <= self.object_association_time:
            self.current_object = closest_object.get("object", None)
            self.last_trigger_id = closest_object.get("id", None)
            self.current_object_time = blink["timestamp"]
            blink["associated"] = True
            self._set_viz_text()
            self._publish_event(blink, events)
            self.logger.debug(f"Blink associated with object: {self.current_object}")
        else:
            self.logger.debug("No object associated with the blink.")

    def _publish_event(self, blink, events):
        """Publish a custom event for a detected blink."""
        custom_datum = {
            "topic": self.CUSTOM_TOPIC,
            "timestamp": blink["timestamp"],
            "object": self.current_object,
            "blink_count": self.discrete_blink_count,  # Use the count of discrete blinks
        }

        # Add the custom event to the events dictionary
        if self.CUSTOM_TOPIC not in events:
            events[self.CUSTOM_TOPIC] = []
        events[self.CUSTOM_TOPIC].append(custom_datum)

        self.logger.debug(f"Published blink event: {custom_datum}")

    def _reset_object(self):
        """Reset the current object after the association time expires."""
        self.logger.debug("Resetting associated object.")
        self.current_object = None
        self.current_object_time = None

    def _set_viz_text(self):
        """Set the visualization text to display the detected gesture."""
        if all([self.last_trigger_id, self.current_object]):
            self.viz_text = (
                f"{self.last_trigger_id} - blink on {self.current_object.upper()}"
            )

    def gl_display(self):
        """Visualize detected blinks and associated objects."""
        # Position where the text will be drawn
        x_legend, y_legend = 20, 700

        # Draw the rounded rectangle
        draw_rounded_rect(
            (x_legend - 10, y_legend - 17),
            (x_legend + (8 * len(self.LEGEND_TEXT)), 23),
            corner_radius=5.0,
            color=self.info_text_bg
        )
        self.glfont.draw_text(x_legend, y_legend, self.LEGEND_TEXT)

        if self.viz_text:
            x, y = 20, 170
            draw_rounded_rect(
                (x - 10, y - 17),
                (x + (8 * len(self.viz_text)), 23),
                corner_radius=5.0,
                color=self.info_text_bg
            )
            self.glfont.draw_text(x, y, self.viz_text)
