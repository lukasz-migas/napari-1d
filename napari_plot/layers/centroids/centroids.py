"""Line layer"""
import numpy as np
from napari.layers.utils.color_transformations import normalize_and_broadcast_colors, transform_color_with_defaults
from napari.utils.events import Event

from ..base import BaseLayer
from ._centroids_constants import Method, Orientation
from ._centroids_utils import get_extents, parse_centroids_data


class Centroids(BaseLayer):
    """Centroids layer

    Parameters
    ----------
    data : array, optional
        Coordinates for N points in 2 dimensions. If array has shape (N, 2) then its assume that its the position and
        upper value and the lower value is assumed to be zero. If array has shape (N, 3) then its assumed that its the
        position, lower value and upper value. X-axis and Y-axis values are inferred based on the orientation attribute.
        Coordinates for N points in 2 dimensions.
    orientation : str or Orientation
        If string, can be `vertical` or `horizontal
    color : str, array-like
        If string can be any color name recognized by vispy or hex value if starting with `#`. If array-like must
        be 1-dimensional array with 3 or 4 elements.
    width : float
        Width of the line in pixel units.
    method : str or Method
        Rendering method. Either `gl` or `agg`.
    label : str
        Label to be displayed in the plot legend. (unused at the moment)
    name : str
        Name of the layer.
    metadata : dict
        Layer metadata.
    scale : tuple of float
        Scale factors for the layer.
    translate : tuple of float
        Translation values for the layer.
    rotate : float, 3-tuple of float, or n-D array.
        If a float convert into a 2D rotation matrix using that value as an angle. If 3-tuple convert into a 3D
        rotation matrix, using a yaw, pitch, roll convention. Otherwise assume an nD rotation. Angles are assumed
        to be in degrees. They can be converted from radians with np.degrees if needed.
    shear : 1-D array or n-D array
        Either a vector of upper triangular values, or an nD shear matrix with ones along the main diagonal.
    affine : n-D array or napari.utils.transforms.Affine
        (N+1, N+1) affine transformation matrix in homogeneous coordinates. The first (N, N) entries correspond to a
        linear transform and the final column is a length N translation vector and a 1 or a napari `Affine` transform
        object. Applied as an extra transform on top of the provided scale, rotate, and shear values.
    opacity : float
        Opacity of the layer visual, between 0.0 and 1.0.
    blending : str
        One of a list of preset blending modes that determines how RGB and alpha values of the layer visual get mixed.
        Allowed values are {'opaque', 'translucent', 'translucent_no_depth', and 'additive'}.
    visible : bool
        Whether the layer visual is currently being displayed.
    """

    def __init__(
        self,
        data,
        *,
        # napari-plot parameters
        orientation="vertical",
        color=(1.0, 1.0, 1.0, 1.0),
        width=2,
        method="gl",
        label="",
        # napari parameters
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
        data = parse_centroids_data(data)
        super().__init__(
            data,
            label=label,
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
        self.events.add(color=Event, width=Event, method=Event, highlight=Event)

        self._data = data
        self._color = self._initialize_color(color, len(self._data))
        self._width = width
        self._method = Method(method)
        self._orientation = Orientation(orientation)

        self.visible = visible

    @staticmethod
    def _initialize_color(color, n_lines: int):
        """Get the face colors the Shapes layer will be initialized with

        Parameters
        ----------
        color : (N, 4) array or str
            The value for setting edge or face_color
        n_lines : int
            Number of lines to be initialized.

        Returns
        -------
        init_colors : (N, 4) array
            The calculated values for setting edge or face_color
        """
        if n_lines > 0:
            transformed_color = transform_color_with_defaults(
                num_entries=n_lines,
                colors=color,
                elem_name="color",
                default="white",
            )
            init_colors = normalize_and_broadcast_colors(n_lines, transformed_color)
        else:
            init_colors = np.empty((0, 4))
        return init_colors

    def update_color(self, index: int, color: np.ndarray):
        """Update color of single line.

        Parameters
        ----------
        index : int
            Index of the line to update the color of.
        color : str | tuple | np.ndarray
            Color of the line.
        """
        self._color[index] = color
        self.events.color()
        self._update_thumbnail()

    @property
    def orientation(self):
        """Orientation of the centroids layer."""
        return self._orientation

    @orientation.setter
    def orientation(self, value):
        self._orientation = Orientation(value)
        self.events.set_data()

    def _update_thumbnail(self):
        """Update thumbnail with current data"""
        if self._allow_thumbnail_update:
            h = self._thumbnail_shape[0]
            thumbnail = np.zeros(self._thumbnail_shape)
            thumbnail[..., 3] = 1
            thumbnail[h - 2 : h + 2, :] = 1  # horizontal strip
            thumbnail[..., 3] *= self.opacity
            self.thumbnail = thumbnail

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
    def data(self):
        """Return data."""
        return self._data

    @data.setter
    def data(self, value: np.ndarray):
        """Update data.

        If the number of centroids is smaller than what's currently set, colors will be trimmed.
        If the number of centroids is larger than what's currently set, colors will be append
        """
        data = parse_centroids_data(value)
        color = self.color
        n = len(self._data)
        n_new = len(data)
        # fewer centroids, trim attributes
        if n > n_new:
            color = self.color[:n_new]
        # more centroids, add attributes
        elif n < n_new:
            n_difference = n_new - n
            new_color = self.color[-1]
            color = np.concatenate([color, np.full((n_difference, 4), fill_value=new_color)])
        self._data = data
        self.color = color
        self._emit_new_data()

    @property
    def color(self):
        """Get color"""
        return self._color

    @color.setter
    def color(self, value):
        self._color = self._initialize_color(value, len(self._data))
        self.events.color()

    @property
    def width(self) -> float:
        """Get width."""
        return self._width

    @width.setter
    def width(self, value: float):
        self._width = value
        self.events.width()

    @property
    def method(self):
        """Get method."""
        return self._method

    @method.setter
    def method(self, value):
        self._method = value
        self.events.method()

    def _set_view_slice(self):
        self.events.set_data()

    def _get_value(self, position):
        """Value of the data at a position in data coordinates"""
        return position[1]

    def _get_state(self):
        """Get dictionary of layer state"""
        state = self._get_base_state()
        state.update(
            {
                "data": self.data,
                "color": self.color,
                "width": self.width,
                "method": self.method,
            }
        )
        return state

    @property
    def _extent_data(self) -> np.ndarray:
        if len(self.data) == 0:
            return np.full((2, 2), np.nan)
        return get_extents(self.data, self.orientation)

    # def _get_x_region_extent(self, x_min: float, x_max: float):
    #     """Return data extents in the (xmin, xmax, ymin, ymax) format."""
    #     from napari_plot.utils.utilities import find_nearest_index
    #
    #     if self.orientation == Orientation.VERTICAL:
    #         idx_min, idx_max = find_nearest_index(self.data[:, 1], [x_min, x_max])
    #         if idx_min == idx_max:
    #             idx_max += 1
