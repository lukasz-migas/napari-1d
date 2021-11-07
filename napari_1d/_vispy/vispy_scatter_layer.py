"""Scatter points layer"""
from typing import TYPE_CHECKING

import numpy as np
from napari._vispy.layers.base import VispyBaseLayer
from napari._vispy.utils.text import update_text
from vispy.scene.visuals import Compound, Markers, Text

if TYPE_CHECKING:
    from ..layers import Scatter


class VispyScatterLayer(VispyBaseLayer):
    """Line layer"""

    def __init__(self, layer: "Scatter"):
        # Create a compound visual with the following two sub-visuals:
        # Markers: The actual markers of each point
        # Text: Text line for each point
        node = Compound([Markers(), Text()])
        super().__init__(layer, node)

        self.layer.events.symbol.connect(self._on_data_change)
        self.layer.events.size.connect(self._on_data_change)
        self.layer.events.edge_width.connect(self._on_data_change)
        self.layer.events.edge_color.connect(self._on_data_change)
        self.layer.events.face_color.connect(self._on_data_change)
        self.layer.events.scaling.connect(self._on_data_change)
        self.layer.text._connect_update_events(self._on_text_change, self._on_blending_change)

        self.reset()
        self._on_data_change()

    def _on_data_change(self, event=None):
        """Set data"""
        set_data = self.node._subvisuals[0].set_data

        set_data(
            self.layer.data[:, ::-1],
            size=self.layer.size,
            edge_width=self.layer.edge_width,
            symbol=self.layer.symbol,
            edge_color=self.layer.edge_color,
            face_color=self.layer.face_color,
            scaling=self.layer.scaling,
        )
        self._on_text_change(update_node=False)
        self.node.update()

    def _on_text_change(self, update_node=True):
        """Function to update the text node properties

        Parameters
        ----------
        update_node : bool
            If true, update the node after setting the properties
        """
        ndisplay = 2
        if self.layer._text.visible is False:
            text_coords = np.zeros((1, ndisplay))
            text = []
            anchor_x = "center"
            anchor_y = "center"
        else:
            text_coords, anchor_x, anchor_y = self.layer._view_text_coords
            if len(text_coords) == 0:
                text_coords = np.zeros((1, ndisplay))
            text = self.layer._view_text
        text_node = self.node._subvisuals[-1]

        update_text(
            text_values=text,
            coords=text_coords,
            anchor=(anchor_x, anchor_y),
            rotation=self.layer._text.rotation,
            color=self.layer._text.color,
            size=self.layer._text.size,
            ndisplay=ndisplay,
            text_node=text_node,
        )
        if update_node:
            self.node.update()
