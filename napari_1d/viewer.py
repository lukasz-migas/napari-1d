"""Viewer instance."""
import typing as ty

from .components.viewer_model import ViewerModel

if ty.TYPE_CHECKING:
    # helpful for IDE support
    from ._qt.qt_main_window import Window


class Viewer(ViewerModel):
    """Napari ndarray viewer.

    Parameters
    ----------
    title : string, optional
        The title of the viewer window. by default 'napari'.
    show : bool, optional
        Whether to show the viewer after instantiation. by default True.
    """

    # Create private variable for window
    _window: "Window"

    def __init__(
        self,
        *,
        title="napari-1d",
        show=True,
    ):
        super().__init__(title=title)
        # having this import here makes all of Qt imported lazily, upon
        # instantiating the first Viewer.
        from .window import Window

        self._window = Window(self, show=show)

    # Expose private window publicly. This is needed to keep window off pydantic model
    @property
    def window(self) -> "Window":
        """Get window"""
        return self._window

    def screenshot(self, path=None, *, canvas_only=True, flash: bool = True):
        """Take currently displayed screen and convert to an image array.

        Parameters
        ----------
        path : str
            Filename for saving screenshot image.
        canvas_only : bool
            If True, screenshot shows only the image display canvas, and
            if False include the napari viewer frame in the screenshot,
            By default, True.
        flash : bool
            Flag to indicate whether flash animation should be shown after
            the screenshot was captured.
            By default, True.

        Returns
        -------
        image : array
            Numpy array of type ubyte and shape (h, w, 4). Index [0, 0] is the
            upper-left corner of the rendered region.
        """
        if canvas_only:
            image = self.window.qt_viewer.screenshot(path=path, flash=flash)
        else:
            image = self.window.screenshot(path=path, flash=flash)
        return image

    def show(self, *, block=False):
        """Resize, show, and raise the viewer window."""
        self.window.show(block=block)

    def close(self):
        """Close the viewer window."""
        # Remove all the layers from the viewer
        self.layers.clear()
        # Close the main window
        self.window.close()
