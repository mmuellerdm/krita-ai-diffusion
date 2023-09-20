from typing import Optional
import krita
from krita import Krita
from .image import Extent, Bounds, Mask, Image
from PyQt5.QtCore import QUuid
from PyQt5.QtGui import QImage


class Document:
    def __init__(self, krita_document):
        self._doc = krita_document

    @staticmethod
    def active():
        doc = Krita.instance().activeDocument()
        return Document(doc) if doc else None

    @property
    def extent(self):
        return Extent(self._doc.width(), self._doc.height())

    @property
    def is_active(self):
        return self._doc == Krita.instance().activeDocument()

    @property
    def is_valid(self):
        return self._doc in Krita.instance().documents()

    def check_color_mode(self):
        model = self._doc.colorModel()
        msg_fmt = "Incompatible document: Color {0} must be {1} (current {0}: {2})"
        if model != "RGBA":
            return False, msg_fmt.format("model", "RGB/Alpha", model)
        depth = self._doc.colorDepth()
        if depth != "U8":
            return False, msg_fmt.format("depth", "8-bit integer", depth)
        return True, None

    def create_mask_from_selection(self):
        user_selection = self._doc.selection()
        if not user_selection:
            return None

        selection = user_selection.duplicate()
        size_factor = Extent(selection.width(), selection.height()).diagonal
        feather_radius = int(0.07 * size_factor)

        selection.grow(feather_radius, feather_radius)
        selection.feather(feather_radius)

        bounds = Bounds(selection.x(), selection.y(), selection.width(), selection.height())
        bounds = Bounds.pad(bounds, feather_radius, multiple=8)
        bounds = Bounds.clamp(bounds, self.extent)
        data = selection.pixelData(*bounds)
        return Mask(bounds, data)

    def get_image(self, bounds: Bounds = None, exclude_layer=None):
        restore_layer = False
        if exclude_layer and exclude_layer.visible():
            exclude_layer.setVisible(False)
            # This is quite slow and blocks the UI. Maybe async spinning on tryBarrierLock works?
            self._doc.refreshProjection()
            restore_layer = True

        bounds = bounds or Bounds(0, 0, self._doc.width(), self._doc.height())
        img = QImage(self._doc.pixelData(*bounds), *bounds.extent, QImage.Format_ARGB32)

        if restore_layer:
            exclude_layer.setVisible(True)
            self._doc.refreshProjection()
        return Image(img)

    def get_layer_image(self, layer, bounds: Bounds):
        return Image(QImage(layer.pixelData(*bounds), *bounds.extent, QImage.Format_ARGB32))

    def insert_layer(
        self, name: str, img: Image, bounds: Bounds, below: Optional[krita.Node] = None
    ):
        layer = self._doc.createNode(name, "paintlayer")
        above = None
        if below:
            nodes = self._doc.rootNode().childNodes()
            index = nodes.index(below)
            if index >= 1:
                above = nodes[index - 1]
        self._doc.rootNode().addChildNode(layer, above)
        layer.setPixelData(img.data, *bounds)
        self._doc.refreshProjection()
        return layer

    def set_layer_content(self, layer, img: Image, bounds: Bounds):
        layer_bounds = Bounds.from_qrect(layer.bounds())
        if layer_bounds != bounds:
            # layer.cropNode(*bounds)  <- more efficient, but clutters the undo stack
            blank = Image.create(layer_bounds.extent, fill=0)
            layer.setPixelData(blank.data, *layer_bounds)
        layer.setPixelData(img.data, *bounds)
        layer.setVisible(True)
        self._doc.refreshProjection()
        return layer

    def hide_layer(self, layer):
        layer.setVisible(False)
        self._doc.refreshProjection()
        return layer

    @property
    def paint_layers(self):
        return [node for node in self._doc.rootNode().childNodes() if node.type() == "paintlayer"]

    def find_layer(self, id: QUuid):
        return next((layer for layer in self.paint_layers if layer.uniqueId() == id), None)

    @property
    def active_layer(self):
        return self._doc.activeNode()