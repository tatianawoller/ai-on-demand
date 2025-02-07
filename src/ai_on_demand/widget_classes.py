from abc import abstractmethod
from pathlib import Path
import string
from typing import Optional
import yaml

import napari
from npe2 import PluginManager
from qtpy.QtWidgets import (
    QWidget,
    QScrollArea,
    QLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
)
from qtpy.QtGui import QPixmap
import qtpy.QtCore

from ai_on_demand.utils import (
    format_tooltip,
    load_settings,
    get_plugin_cache,
    merge_dicts,
)


class MainWidget(QWidget):
    def __init__(
        self,
        napari_viewer: napari.Viewer,
        title: str,
        tooltip: Optional[str] = None,
    ):
        super().__init__()
        pm = PluginManager.instance()
        self.all_manifests = pm.commands.execute("ai-on-demand.get_manifests")
        self.plugin_settings = pm.commands.execute("ai-on-demand.get_settings")

        self.viewer = napari_viewer
        self.scroll = QScrollArea()

        # Set overall layout for the widget
        self.setLayout(QVBoxLayout())

        # Dictionary to contain all subwidgets
        self.subwidgets = {}

        # Add a Crick logo to the widget
        self.logo_label = QLabel()
        logo = QPixmap(
            str(
                Path(__file__).parent
                / "resources"
                / "CRICK_Brandmark_01_transparent.png"
            )
        ).scaledToHeight(100, mode=qtpy.QtCore.Qt.SmoothTransformation)
        self.logo_label.setPixmap(logo)
        self.logo_label.setAlignment(qtpy.QtCore.Qt.AlignCenter)
        self.layout().addWidget(self.logo_label)

        # Widget title to display
        self.title = QLabel(f"AI OnDemand: {title}")
        title_font = self.font()
        title_font.setPointSize(16)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.title.setAlignment(qtpy.QtCore.Qt.AlignCenter)
        if tooltip is not None:
            self.tooltip = tooltip
            self.title.setToolTip(format_tooltip(tooltip))
        self.layout().addWidget(self.title)

        # Create the widget that will be used to add subwidgets to
        # This is then the widget for the scroll area, to the logo/title is excluded from scrolling
        self.content_widget = QWidget()
        self.content_widget.setLayout(QVBoxLayout())
        self.scroll.setWidgetResizable(True)
        # This is needed to avoid unnecessary spacing when in the ScrollArea
        self.content_widget.setSizePolicy(
            qtpy.QtWidgets.QSizePolicy.Minimum,
            qtpy.QtWidgets.QSizePolicy.Fixed,
        )
        self.scroll.setWidget(self.content_widget)
        self.layout().addWidget(self.scroll)

    def register_widget(self, widget: "SubWidget"):
        self.subwidgets[widget._name] = widget

    def store_settings(self):
        # Check for each of the things we want to store
        # Skipping if not present in this main widget
        if "nxf" in self.subwidgets:
            self.plugin_settings["nxf"] = self.subwidgets["nxf"].get_settings()

        # Load the existing saved settings
        orig_settings = load_settings()
        # Merge the current settings
        # Try to do a nuanced merge at first
        try:
            plugin_settings = merge_dicts(orig_settings, self.plugin_settings)
        except KeyError:
            # If this fails, our schema has changed and we need to overwrite the settings
            # Try to preserve original where possible
            # TODO: Future, embed versioning in the settings
            plugin_settings = {**orig_settings, **self.plugin_settings}
        # Save the settings to the cache
        _, settings_path = get_plugin_cache()
        with open(settings_path, "w") as f:
            yaml.dump(plugin_settings, f)


class SubWidget(QWidget):
    # Define a shorthand name to be used to register the widget
    _name: str = None

    def __init__(
        self,
        viewer: napari.Viewer,
        title: str,
        parent: Optional[QWidget] = None,
        layout: QLayout = QGridLayout,
        tooltip: Optional[str] = None,
    ):
        """
        Custom widget for the AI OnDemand plugin.

        Controls the subwidgets/modules of the plugin which are used for different meta-plugins.
        Allows for easy changes of style, uniform layout, and better interoperability between other subwidgets.

        Parameters
        ----------
        viewer : napari.Viewer
            Napari viewer object.
        parent : QWidget, optional
            Parent widget, by default None. Allows for easy access to the parent widget and its attributes.
        title : str
            Title of the widget to be displayed.
        layout : QLayout, optional
            Layout to use for the widget, by default QGridLayout. This is the default layout for the subwidget.
        tooltip : Optional[str], optional
            Tooltip to display for the widget (i.e. the GroupBox), by default None.
        """
        super().__init__()
        self.viewer = viewer
        self.parent = parent

        # Set the layout
        self.setLayout(layout())
        # Set the main widget container
        self.widget = QGroupBox(f"{string.capwords(title)}:")
        if tooltip is not None:
            self.widget.setToolTip(format_tooltip(tooltip))
        # Create the initial widgets/elements
        self.create_box()

        # If given a parent at creation, add this widget to the parent's layout
        if self.parent is not None:
            # Add to the content widget (i.e. scrollable able)
            self.parent.content_widget.layout().addWidget(self.widget)

        self.load_settings()

    @abstractmethod
    def create_box(self, variant: Optional[str] = None):
        """
        Create the box for the subwidget, i.e. all UI elements.
        """
        raise NotImplementedError

    @abstractmethod
    def load_settings(self):
        """
        Load settings for the subwidget.
        """
        pass

    @abstractmethod
    def get_settings(self):
        """
        Get settings for the subwidget.
        """
        pass
