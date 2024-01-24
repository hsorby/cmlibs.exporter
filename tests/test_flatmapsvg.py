import os.path
import unittest
import xml.etree.ElementTree as ET

from cmlibs.zinc.context import Context

from cmlibs.exporter import flatmapsvg


here = os.path.abspath(os.path.dirname(__file__))


def _resource_path(resource_name):
    return os.path.join(here, "resources", resource_name)


class Exporter(unittest.TestCase):

    def test_flatmap_svg(self):
        source_model = _resource_path("flattened_vagus.exf")
        output_target = _resource_path("")

        exporter = flatmapsvg.ArgonSceneExporter(output_target=output_target, output_prefix="flatmap")

        c = Context('generate_flatmap_svg')
        root_region = c.getDefaultRegion()
        root_region.readFile(source_model)

        exporter.export_from_scene(root_region.getScene())
        flatmap_svg_file = _resource_path("flatmap.svg")
        self.assertTrue(os.path.isfile(flatmap_svg_file))

        tree = ET.parse(flatmap_svg_file)
        root = tree.getroot()

        self.assertEqual(58, len(root))

        os.remove(flatmap_svg_file)