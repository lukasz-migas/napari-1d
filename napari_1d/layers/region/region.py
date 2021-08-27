"""Infinite region"""
from contextlib import contextmanager
from copy import copy
from typing import Tuple

import numpy as np
from napari.layers.base import Layer, no_op
from napari.layers.shapes._shapes_constants import Box
from napari.layers.shapes._shapes_utils import create_box
from napari.layers.utils.color_transformations import normalize_and_broadcast_colors, transform_color_with_defaults
from napari.utils.events import Event
from napari.utils.misc import ensure_iterable

from ._region_constants import Mode, Orientation, region_classes
from ._region_list import RegionList
from ._region_utils import extract_region_orientation, get_default_region_type, preprocess_region


class Region(Layer):
    """Line layer"""

    _drag_modes = {Mode.ADD: no_op, Mode.MOVE: no_op, Mode.SELECT: no_op, Mode.PAN_ZOOM: no_op}
    _move_modes = {Mode.ADD: no_op, Mode.SELECT: no_op, Mode.PAN_ZOOM: no_op, Mode.MOVE: no_op}
    _cursor_modes = {Mode.ADD: "pointing", Mode.MOVE: "pointing", Mode.PAN_ZOOM: "standard", Mode.SELECT: "pointing"}

    def __init__(
        self,
        data,
        *,
        orientation="vertical",
        label="",
        edge_width=1,
        edge_color="red",
        face_color="white",
        z_index=0,
        # base parameters
        name=None,
        metadata=None,
        scale=None,
        translate=None,
        rotate=None,
        shear=None,
        affine=None,
        opacity=1.0,
        blending="translucent",
        visible=True,
    ):
        # sanitize data
        if data is None:
            data = np.asarray([])
        else:
            data, orientation = extract_region_orientation(data, orientation)
        super().__init__(
            data,
            ndim=2,
            name=name,
            metadata=metadata,
            scale=scale,
            translate=translate,
            rotate=rotate,
            shear=shear,
            affine=affine,
            opacity=opacity,
            blending=blending,
            visible=visible,
        )
        self.events.add(
            edge_width=Event,
            edge_color=Event,
            face_color=Event,
            current_edge_color=Event,
            current_face_color=Event,
            highlight=Event,
            label=Event,
            mode=Event,
            shifted=Event,
            accept=Event,
        )
        # Flag set to false to block thumbnail refresh
        self._allow_thumbnail_update = True

        self._display_order_stored = []
        self._ndisplay_stored = self._ndisplay

        self._label = label

        # The following shape properties are for the new shapes that will
        # be drawn. Each shape has a corresponding property with the
        # value for itself
        if np.isscalar(edge_width):
            self._current_edge_width = edge_width
        else:
            self._current_edge_width = 1

        self._data_view = RegionList(ndisplay=self._ndisplay)
        self._data_view.slice_key = np.array(self._slice_indices)[list(self._dims_not_displayed)]

        # indices of selected lines
        self._value = (None, None)
        self._value_stored = (None, None)
        self._selected_data = set()
        self._selected_data_stored = set()
        self._selected_box = None

        self._drag_start = None
        self._drag_box = None
        self._drag_box_stored = None
        self._is_creating = False
        self._is_selecting = False
        self._moving_coordinates = None
        self._is_moving = False

        # change mode once to trigger the
        # Mode setting logic
        self._mode = Mode.SELECT
        self.mode = Mode.PAN_ZOOM
        self._status = self.mode

        self._init_regions(
            data,
            orientation=orientation,
            edge_width=edge_width,
            edge_color=edge_color,
            face_color=face_color,
            z_index=z_index,
        )

        # set the current_* properties
        if len(data) > 0:
            self._current_edge_color = self.edge_color[-1]
            self._current_face_color = self.face_color[-1]
        elif len(data) == 0:
            self._current_edge_color = transform_color_with_defaults(
                num_entries=1,
                colors=edge_color,
                elem_name="edge_color",
                default="black",
            )
            self._current_face_color = transform_color_with_defaults(
                num_entries=1,
                colors=face_color,
                elem_name="face_color",
                default="black",
            )
        self.visible = visible

    # noinspection PyMethodMayBeStatic
    def _initialize_color(self, color, attribute, n_regions: int):
        """Get the face/edge colors the Shapes layer will be initialized with

        Parameters
        ----------
        color : (N, 4) array or str
            The value for setting edge or face_color

        Returns
        -------
        init_colors : (N, 4) array or str
            The calculated values for setting edge or face_color
        """
        if n_regions > 0:
            transformed_color = transform_color_with_defaults(
                num_entries=n_regions,
                colors=color,
                elem_name="face_color",
                default="white",
            )
            init_colors = normalize_and_broadcast_colors(n_regions, transformed_color)
        else:
            init_colors = np.empty((0, 4))
        return init_colors

    @contextmanager
    def block_thumbnail_update(self):
        """Use this context manager to block thumbnail updates"""
        self._allow_thumbnail_update = False
        yield
        self._allow_thumbnail_update = True

    @property
    def edge_color(self):
        """(N x 4) np.ndarray: Array of RGBA face colors for each shape"""
        return self._data_view.edge_color

    @edge_color.setter
    def edge_color(self, edge_color):
        self._set_color(edge_color, "edge")
        self.events.edge_color()
        self._update_thumbnail()

    @property
    def face_color(self):
        """(N x 4) np.ndarray: Array of RGBA face colors for each shape"""
        return self._data_view.face_color

    @face_color.setter
    def face_color(self, face_color):
        self._set_color(face_color, "face")
        self.events.face_color()
        self._update_thumbnail()

    @property
    def edge_width(self):
        """list of float: edge width for each shape."""
        return self._data_view.edge_widths

    @edge_width.setter
    def edge_width(self, width):
        """Set edge width of shapes using float or list of float.

        If list of float, must be of equal length to n shapes

        Parameters
        ----------
        width : float or list of float
            width of all shapes, or each shape if list
        """
        if isinstance(width, list):
            if not len(width) == self.n_regions:
                raise ValueError("Length of list does not match number of orientations.")
            else:
                widths = width
        else:
            widths = [width for _ in range(self.n_regions)]

        for i, width in enumerate(widths):
            self._data_view.update_edge_width(i, width)

    @property
    def current_edge_width(self):
        """float: Width of shape edges including lines and paths."""
        return self._current_edge_width

    @current_edge_width.setter
    def current_edge_width(self, edge_width):
        self._current_edge_width = edge_width
        if self._update_properties:
            for i in self.selected_data:
                self._data_view.update_edge_width(i, edge_width)
        self.events.edge_width()

    @property
    def z_index(self):
        """list of int: z_index for each shape."""
        return self._data_view.z_indices

    @z_index.setter
    def z_index(self, z_index):
        """Set z_index of shape using either int or list of int.

        When list of int is provided, must be of equal length to n shapes.

        Parameters
        ----------
        z_index : int or list of int
            z-index of shapes
        """
        if isinstance(z_index, list):
            if not len(z_index) == self.n_regions:
                raise ValueError("Length of list does not match number of orientations.")
            else:
                z_indices = z_index
        else:
            z_indices = [z_index for _ in range(self.n_regions)]

        for i, z_idx in enumerate(z_indices):
            self._data_view.update_z_index(i, z_idx)

    def accept(self):
        """Emit accept event"""
        self.events.accept()

    @property
    def mode(self) -> str:
        """str: Interactive mode

        Interactive mode. The normal, default mode is PAN_ZOOM, which
        allows for normal interactivity with the canvas.

        In MOVE the region is moved to new location
        """
        return str(self._mode)

    @mode.setter
    def mode(self, mode):
        mode, changed = self._mode_setter_helper(mode, Mode)
        if not changed:
            return

        assert mode is not None, mode
        old_mod = self._mode

        if mode == Mode.ADD:
            self.selected_data = set()
            self.interactive = False

        if mode == Mode.PAN_ZOOM:
            self.help = ""
            self.interactive = True
        else:
            self.help = "Hold <space> to pan/zoom."

        if mode != Mode.SELECT or old_mod != Mode.SELECT:
            self._selected_data_stored = set()

        self._mode = mode
        self._set_highlight()
        self.events.mode(mode=mode)

    @property
    def selected_data(self) -> set:
        """set: set of currently selected points."""
        return self._selected_data

    @selected_data.setter
    def selected_data(self, selected_data):
        self._selected_data = set(selected_data)

    def remove_selected(self):
        """Remove any selected shapes."""
        index = list(self.selected_data)
        to_remove = sorted(index, reverse=True)
        for ind in to_remove:
            self._data_view.remove(ind)

        if len(index) > 0:
            self._data_view._edge_color = np.delete(self._data_view._edge_color, index, axis=0)
            self._data_view._face_color = np.delete(self._data_view._face_color, index, axis=0)
        self.selected_data = set()
        self._finish_drawing()
        self.events.data(value=self.data)

    def move(
        self,
        start_coords: Tuple[float],
        end_coords: Tuple[float],
        finished: bool = False,
    ):
        """Move region to new location"""

    #     if self.is_vertical:
    #         start, end = start_coords[1], end_coords[1]
    #     else:
    #         start, end = start_coords[0], end_coords[0]
    #     self.data = np.asarray([start, end])
    #     if finished:
    #         self.events.shifted()

    def _get_ndim(self):
        """Determine number of dimensions of the layer"""
        return 2

    def _get_state(self):
        """Get dictionary of layer state"""
        state = self._get_base_state()
        state.update({"data": self.data, "color": self.color, "label": self.label})
        return state

    def _update_thumbnail(self):
        """Update thumbnail with current data"""
        colormapped = np.zeros(self._thumbnail_shape)
        colormapped[..., 3] = 1
        colormapped[..., 3] *= self.opacity
        self.thumbnail = colormapped

    @property
    def _view_data(self) -> np.ndarray:
        """Get the coords of the points in view

        Returns
        -------
        view_data : (N x D) np.ndarray
            Array of coordinates for the N points in view
        """
        return self.data

    @property
    def n_regions(self) -> int:
        """Get number of regions."""
        return len(self._data_view.regions)

    @property
    def data(self):
        """Return data"""
        return self._data_view.data

    @data.setter
    def data(self, data):
        data, orientation = extract_region_orientation(data)
        n_new_regions = len(data)
        if orientation is None:
            orientation = self.orientation

        edge_widths = self._data_view.edge_widths
        edge_color = self._data_view.edge_color
        face_color = self._data_view.face_color
        z_indices = self._data_view.z_indices

        # fewer shapes, trim attributes
        if self.n_regions > n_new_regions:
            orientation = orientation[:n_new_regions]
            edge_widths = edge_widths[:n_new_regions]
            z_indices = z_indices[:n_new_regions]
            edge_color = edge_color[:n_new_regions]
            face_color = face_color[:n_new_regions]
        # more shapes, add attributes
        elif self.n_regions < n_new_regions:
            n_shapes_difference = n_new_regions - self.n_regions
            orientation = orientation + [get_default_region_type(orientation)] * n_shapes_difference
            edge_widths = edge_widths + [1] * n_shapes_difference
            z_indices = z_indices + [0] * n_shapes_difference
            edge_color = np.concatenate(
                (
                    edge_color,
                    self._get_new_shape_color(n_shapes_difference, "edge"),
                )
            )
            face_color = np.concatenate(
                (
                    face_color,
                    self._get_new_shape_color(n_shapes_difference, "face"),
                )
            )

        self._data_view = RegionList()
        self.add(
            data,
            orientation=orientation,
            edge_width=edge_widths,
            edge_color=edge_color,
            face_color=face_color,
            z_index=z_indices,
        )

        self._update_dims()
        self.events.data(value=self.data)
        self._set_editable()

    def add(
        self,
        data,
        *,
        orientation="vertical",
        edge_width=None,
        edge_color=None,
        face_color=None,
        z_index=None,
    ):
        """Add shapes to the current layer.

        Parameters
        ----------
        data : Array | Tuple(Array,str) | List[Array | Tuple(Array, str)] | Tuple(List[Array], str)
            List of shape data, where each element is either an (N, D) array of the
            N vertices of a shape in D dimensions or a tuple containing an array of
            the N vertices and the shape_type string. When a shape_type is present,
            it overrides keyword arg shape_type. Can be an 3-dimensional array
            if each shape has the same number of vertices.
        orientation : string | list
            String of orientation type, must be one of "{'vertical', 'horizontal'}.
            If list is supplied it must be the same length as the length of `data`
            and each element will be applied to each region otherwise the same
            value will be used for all regions. Override by data orientation, if present.
        edge_width : float | list
            thickness of lines and edges. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        edge_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        face_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        z_index : int | list
            Specifier of z order priority. Shapes with higher z order are
            displayed on top of others. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        """
        data, shape_type = extract_region_orientation(data, orientation)

        if edge_width is None:
            edge_width = self.current_edge_width

        n_new_shapes = len(data)
        if edge_color is None:
            edge_color = self._get_new_region_color(n_new_shapes, attribute="edge")
        if face_color is None:
            face_color = self._get_new_region_color(n_new_shapes, attribute="face")
        if self._data_view is not None:
            z_index = z_index or max(self._data_view._z_index, default=-1) + 1
        else:
            z_index = z_index or 0

        if n_new_shapes > 0:
            self._add_regions(
                data,
                orientation=orientation,
                edge_width=edge_width,
                edge_color=edge_color,
                face_color=face_color,
                z_index=z_index,
            )
            self.events.data(value=self.data)

    def _add_regions(
        self,
        data,
        *,
        orientation="vertical",
        edge_width=None,
        edge_color=None,
        face_color=None,
        z_index=None,
        z_refresh=True,
    ):
        """Add shapes to the data view.

        Parameters
        ----------
        data : Array | Tuple(Array,str) | List[Array | Tuple(Array, str)] | Tuple(List[Array], str)
            List of shape data, where each element is either an (N, D) array of the
            N vertices of a shape in D dimensions or a tuple containing an array of
            the N vertices and the shape_type string. When a shape_type is present,
            it overrides keyword arg shape_type. Can be an 3-dimensional array
            if each shape has the same number of vertices.
        orientation : string | list
            String of orientation type, must be one of "{'vertical', 'horizontal'}.
            If list is supplied it must be the same length as the length of `data`
            and each element will be applied to each region otherwise the same
            value will be used for all regions. Override by data orientation, if present.
        edge_width : float | list
            thickness of lines and edges. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        edge_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        face_color : str | tuple | list
            If string can be any color name recognized by vispy or hex value if
            starting with `#`. If array-like must be 1-dimensional array with 3
            or 4 elements. If a list is supplied it must be the same length as
            the length of `data` and each element will be applied to each shape
            otherwise the same value will be used for all shapes.
        z_index : int | list
            Specifier of z order priority. Shapes with higher z order are
            displayed on top of others. If a list is supplied it must be the
            same length as the length of `data` and each element will be
            applied to each shape otherwise the same value will be used for all
            shapes.
        z_refresh : bool
            If set to true, the mesh elements are re-indexed with the new z order.
            When shape_index is provided, z_refresh will be overwritten to false,
            as the z indices will not change.
            When adding a batch of shapes, set to false  and then call
            ShapesList._update_z_order() once at the end.
        """
        if edge_width is None:
            edge_width = self.current_edge_width
        if edge_color is None:
            edge_color = self._current_edge_color
        if face_color is None:
            face_color = self._current_face_color
        if self._data_view is not None:
            z_index = z_index or max(self._data_view._z_index, default=-1) + 1
        else:
            z_index = z_index or 0

        if len(data) > 0:
            # transform the colors
            transformed_ec = transform_color_with_defaults(
                num_entries=len(data),
                colors=edge_color,
                elem_name="edge_color",
                default="white",
            )
            transformed_edge_color = normalize_and_broadcast_colors(len(data), transformed_ec)
            transformed_fc = transform_color_with_defaults(
                num_entries=len(data),
                colors=face_color,
                elem_name="face_color",
                default="white",
            )
            transformed_face_color = normalize_and_broadcast_colors(len(data), transformed_fc)

            # Turn input arguments into iterables
            region_inputs = zip(
                data,
                ensure_iterable(orientation),
                ensure_iterable(edge_width),
                transformed_edge_color,
                transformed_face_color,
                ensure_iterable(z_index),
            )
            self._add_regions_to_view(region_inputs, self._data_view)

        self._display_order_stored = copy(self._dims_order)
        self._ndisplay_stored = copy(self._ndisplay)
        self._update_dims()

    def _get_new_region_color(self, adding: int, attribute: str):
        """Get the color for the shape(s) to be added.

        Parameters
        ----------
        adding : int
            the number of shapes that were added
            (and thus the number of color entries to add)
        attribute : str in {'edge', 'face'}
            The name of the attribute to set the color of.
            Should be 'edge' for edge_color_mode or 'face' for face_color_mode.

        Returns
        -------
        new_colors : (N, 4) array
            (Nx4) RGBA array of colors for the N new shapes
        """
        current_face_color = getattr(self, f"_current_{attribute}_color")
        new_colors = np.tile(current_face_color, (adding, 1))
        return new_colors

    def _init_regions(self, data, *, orientation=None, edge_width=None, edge_color=None, face_color=None, z_index=None):
        """Add regions to the data view."""
        n_regions = len(data)
        edge_color = self._initialize_color(edge_color, attribute="edge", n_regions=n_regions)
        face_color = self._initialize_color(face_color, attribute="face", n_regions=n_regions)
        with self.block_thumbnail_update():
            self._add_regions(
                data,
                orientation=orientation,
                edge_width=edge_width,
                edge_color=edge_color,
                face_color=face_color,
                z_index=z_index,
                z_refresh=False,
            )
            self._data_view._update_z_order()

    def _add_regions_to_view(self, shape_inputs, data_view):
        """Build new region and add them to the _data_view"""
        for d, ot, ew, ec, fc, z in shape_inputs:
            region_cls = region_classes[Orientation(ot)]
            d = preprocess_region(d, ot)
            region = region_cls(d, edge_width=ew, z_index=z, dims_order=self._dims_order, ndisplay=self._ndisplay)

            # Add region
            data_view.add(region, edge_color=ec, face_color=fc, z_refresh=False)
        data_view._update_z_order()

    @property
    def orientation(self):
        """Orientation of the infinite region."""
        return self._data_view.orientations

    # @orientation.setter
    # def orientation(self, orientation):
    #     self._finish_drawing()
    #
    #     new_data_view = RegionList()
    #     shape_inputs = zip(
    #         self._data_view.data,
    #         ensure_iterable(orientation),
    #         self._data_view.edge_widths,
    #         self._data_view.edge_color,
    #         self._data_view.face_color,
    #         self._data_view.z_indices,
    #     )
    #
    #     self._add_regions_to_view(shape_inputs, new_data_view)
    #
    #     self._data_view = new_data_view
    #     self._update_dims()

    @property
    def label(self):
        """Get label"""
        return self._label

    @label.setter
    def label(self, value):
        self._label = value
        self.events.label()

    def _set_view_slice(self):
        pass

    def _get_value(self, position):
        """Value of the data at a position in data coordinates"""
        return None

    @property
    def _extent_data(self) -> np.ndarray:
        return np.full((2, 2), np.nan)

    def _set_highlight(self, force=False):
        """Render highlights.

        Parameters
        ----------
        force : bool
            Bool that forces a redraw to occur when `True`.
        """
        # Check if any shape or vertex ids have changed since last call
        if (
            self.selected_data == self._selected_data_stored
            and np.all(self._value == self._value_stored)
            and np.all(self._drag_box == self._drag_box_stored)
        ) and not force:
            return
        self._selected_data_stored = copy(self.selected_data)
        self._value_stored = copy(self._value)
        self._drag_box_stored = copy(self._drag_box)
        self.events.highlight()

    def _compute_vertices_and_box(self):
        """Compute location of highlight vertices and box for rendering.

        Returns
        -------
        vertices : np.ndarray
            Nx2 array of any vertices to be rendered as Markers
        face_color : str
            String of the face color of the Markers
        edge_color : str
            String of the edge color of the Markers and Line for the box
        pos : np.ndarray
            Nx2 array of vertices of the box that will be rendered using a
            Vispy Line
        width : float
            Width of the box edge
        """
        if len(self.selected_data) > 0:
            if self._mode == Mode.SELECT:
                # If in select mode just show the interaction bounding box
                # including its vertices and the rotation handle
                box = self._selected_box[Box.WITH_HANDLE]
                if self._value[0] is None:
                    face_color = "white"
                elif self._value[1] is None:
                    face_color = "white"
                else:
                    face_color = self._highlight_color
                edge_color = self._highlight_color
                vertices = box[:, ::-1]
                # Use a subset of the vertices of the interaction_box to plot
                # the line around the edge
                pos = box[Box.LINE_HANDLE][:, ::-1]
                width = 1.5
            else:
                # Otherwise show nothing
                vertices = np.empty((0, 2))
                face_color = "white"
                edge_color = "white"
                pos = None
                width = 0
        elif self._is_selecting:
            # If currently dragging a selection box just show an outline of
            # that box
            vertices = np.empty((0, 2))
            edge_color = self._highlight_color
            face_color = "white"
            box = create_box(self._drag_box)
            width = 1.5
            # Use a subset of the vertices of the interaction_box to plot
            # the line around the edge
            pos = box[Box.LINE][:, ::-1]
        else:
            # Otherwise show nothing
            vertices = np.empty((0, 2))
            face_color = "white"
            edge_color = "white"
            pos = None
            width = 0
        return vertices, face_color, edge_color, pos, width

    def _finish_drawing(self, event=None):
        """Reset properties used in shape drawing."""
        self._is_moving = False
        self.selected_data = set()
        self._drag_start = None
        self._drag_box = None
        self._is_selecting = False
        self._value = (None, None)
        self._moving_value = (None, None)
        self._update_dims()

    def move_to_front(self):
        """Moves selected objects to be displayed in front of all others."""
        if len(self.selected_data) == 0:
            return
        new_z_index = max(self._data_view._z_index) + 1
        for index in self.selected_data:
            self._data_view.update_z_index(index, new_z_index)
        self.refresh()

    def move_to_back(self):
        """Moves selected objects to be displayed behind all others."""
        if len(self.selected_data) == 0:
            return
        new_z_index = min(self._data_view._z_index) - 1
        for index in self.selected_data:
            self._data_view.update_z_index(index, new_z_index)
        self.refresh()
