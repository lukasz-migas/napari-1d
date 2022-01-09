"""Example showing how to plot multiple line sand adjust axis labels."""
import napari_1d
import numpy as np

viewer1d = napari_1d.Viewer()
x = np.arange(0.0, 2.0, 0.01)
viewer1d.add_line(np.c_[x + 0.25, 1 + np.sin(2 * np.pi * x)], name="Sin", color="#FF0000")
viewer1d.add_line(np.c_[x + 0.25, 1 + np.cos(2 * np.pi * x)], name="Cos", color="#0000FF")
viewer1d.axis.x_label = "time (s)"
viewer1d.axis.y_label = "voltage (mV)"
napari_1d.run()
