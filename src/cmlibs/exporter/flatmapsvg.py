"""
Export an Argon document to source document(s) suitable for the generating
flatmaps from.
"""
import csv
import json
import os
import random

from svgpathtools import svg2paths
from xml.dom.minidom import parseString

from cmlibs.zinc.field import Field
from cmlibs.zinc.result import RESULT_OK

from cmlibs.exporter.base import BaseExporter
from cmlibs.maths.vectorops import sub, div, add
from cmlibs.utils.zinc.field import get_group_list
from cmlibs.utils.zinc.general import ChangeManager


SVG_COLOURS = [
    "aliceblue", "aquamarine", "azure", "blanchedalmond", "blue", "blueviolet", "brown", "burlywood",
    "cadetblue", "chartreuse", "chocolate", "coral", "cornflowerblue", "cornsilk", "crimson", "cyan",
    "darkblue", "darkcyan", "darkgoldenrod", "darkgray", "darkgreen", "darkgrey", "darkkhaki", "darkmagenta",
    "darkolivegreen", "darkorange", "darkorchid", "darkred", "darksalmon", "darkseagreen", "darkslateblue",
    "darkslategray", "darkslategrey", "darkturquoise", "darkviolet", "deeppink", "deepskyblue", "dimgray",
    "dimgrey", "dodgerblue", "firebrick", "floralwhite", "forestgreen", "fuchsia", "gainsboroghost",
    "whitegold", "goldenrod", "gray", "green", "greenyellow", "grey", "honeydew", "hotpink", "indianred",
    "indigo", "ivorykhakilavender", "lavenderblush", "lawngreen", "lemonchiffon", "lightblue", "lightcoral",
    "lightcyan", "lightgolden", "rodyellow", "lightgray", "lightgreen", "lightgrey", "lightpink",
    "lightsalmon", "lightseagreen",
]


class ArgonSceneExporter(BaseExporter):
    """
    Export a visualisation described by an Argon document to webGL.
    """

    def __init__(self, output_target=None, output_prefix=None):
        """
        :param output_target: The target directory to export the visualisation to.
        :param output_prefix: The prefix for the exported file(s).
        """
        super(ArgonSceneExporter, self).__init__("ArgonSceneExporterWavefrontSVG" if output_prefix is None else output_prefix)
        self._output_target = output_target
        self._annotations_csv_file = None

    def export(self, output_target=None):
        """
        Export the current document to *output_target*. If no *output_target* is given then
        the *output_target* set at initialisation is used.

        If there is no current document then one will be loaded from the current filename.

        :param output_target: Output directory location.
        """
        super().export()

        if output_target is not None:
            self._output_target = output_target

        self.export_flatmapsvg()

    def export_from_scene(self, scene, scene_filter=None):
        """
        Export graphics from a Zinc Scene into Flatmap SVG format.

        :param scene: The Zinc Scene object to be exported.
        :param scene_filter: Optional; A Zinc Scenefilter object associated with the Zinc scene, allowing the user to filter which
            graphics are included in the export.
        """
        self.export_flatmapsvg_from_scene(scene, scene_filter)

    def export_flatmapsvg(self):
        """
        Export graphics into JSON format, one json export represents one Zinc graphics.
        """
        scene = self._document.getRootRegion().getZincRegion().getScene()
        self.export_flatmapsvg_from_scene(scene)

    def export_flatmapsvg_from_scene(self, scene, scene_filter=None):
        """
        Export graphics from a Zinc Scene into Flatmap SVG format.

        :param scene: The Zinc Scene object to be exported.
        :param scene_filter: Optional; A Zinc Scenefilter object associated with the Zinc scene, allowing the user to filter which
            graphics are included in the export.
        """
        region = scene.getRegion()
        path_points = _analyze_elements(region, "coordinates")
        bezier = _calculate_bezier_control_points(path_points)
        markers = _calculate_markers(region, "coordinates")
        svg_string = _write_into_svg_format(bezier, markers)
        paths, attributes = svg2paths(svg_string)
        bbox = [999999999, -999999999, 999999999, -999999999]
        for p in paths:
            path_bbox = p.bbox()
            bbox[0] = min(path_bbox[0], bbox[0])
            bbox[1] = max(path_bbox[1], bbox[1])
            bbox[2] = min(path_bbox[2], bbox[2])
            bbox[3] = max(path_bbox[3], bbox[3])

        view_margin = 10
        view_box = (int(bbox[0] + 0.5) - view_margin,
                    int(bbox[2] + 0.5) - view_margin,
                    int(bbox[1] - bbox[0] + 0.5) + 2 * view_margin,
                    int(bbox[3] - bbox[2] + 0.5) + 2 * view_margin)

        svg_string = svg_string.replace('viewBox="WWW XXX YYY ZZZ"', f'viewBox="{view_box[0]} {view_box[1]} {view_box[2]} {view_box[3]}"')

        svg_string = parseString(svg_string).toprettyxml()

        reversed_map = None
        if self._annotations_csv_file is not None:
            with open(self._annotations_csv_file) as fh:
                result = csv.reader(fh)

                is_annotation_csv_file = _is_annotation_csv_file(result)

                if is_annotation_csv_file:
                    fh.seek(0)
                    reversed_map = _reverse_map_annotations(result)

        features = {}
        centreline_names = []
        for path_key in path_points:
            if _is_group_svg_id(path_key):
                centreline_names.append(path_key)
                features[path_key] = {
                    "label": path_points[path_key],
                    "type": "centreline",
                }
                if reversed_map is not None and _label_has_annotations(path_points[path_key], reversed_map):
                    features[path_key]["models"] = reversed_map[path_points[path_key]]

        networks = []
        centrelines = []
        for centreline_name in centreline_names:
            centrelines.append({"id": centreline_name})

        # May at some point be able to describe the connectivity between centrelines.
        # networks.append({"centrelines": centrelines})

        for marker in markers:
            feature = {
                "name": marker[2],
                "models": marker[3],
                "colour": "orange"
            }
            features[marker[0]] = feature

        properties = {"features": features, "networks": networks}

        with open(f'{os.path.join(self._output_target, self._prefix)}.svg', 'w') as f:
            f.write(svg_string)

        with open(os.path.join(self._output_target, 'properties.json'), 'w') as f:
            json.dump(properties, f, default=lambda o: o.__dict__, sort_keys=True, indent=2)

    def set_annotations_csv_file(self, filename):
        self._annotations_csv_file = filename


def _calculate_markers(region, coordinate_field_name):
    probable_group_names = ['marker', 'markers']
    fm = region.getFieldmodule()
    coordinate_field = fm.findFieldByName('marker_data_coordinates').castFiniteElement()
    name_field = fm.findFieldByName('marker_data_name')
    id_field = fm.findFieldByName('marker_data_id')

    markers_group = Field()
    for probable_group_name in probable_group_names:
        markers_group = fm.findFieldByName(probable_group_name)
        if markers_group.isValid():
            break

    marker_data = []
    if markers_group.isValid():
        markers_group = markers_group.castGroup()
        marker_node_set = fm.findNodesetByFieldDomainType(Field.DOMAIN_TYPE_DATAPOINTS)
        marker_datapoints = markers_group.getNodesetGroup(marker_node_set)
        marker_iterator = marker_datapoints.createNodeiterator()
        components_count = coordinate_field.getNumberOfComponents()

        marker = marker_iterator.next()
        fc = fm.createFieldcache()

        i = 0
        while marker.isValid():
            fc.setNode(marker)
            result, values = coordinate_field.evaluateReal(fc, components_count)
            if name_field.isValid():
                name = name_field.evaluateString(fc)
            else:
                name = f"Unnamed marker {i + 1}"

            if id_field.isValid():
                onto_id = id_field.evaluateString(fc)
            else:
                rand_num = random.randint(1, 99999)
                onto_id = f"UBERON:99{rand_num:0=5}"
            marker_data.append((f"marker_{marker.getIdentifier()}", values[:2], name, onto_id))
            marker = marker_iterator.next()
            i += 1

    return marker_data


def _group_svg_id(group_name):
    return group_name.replace("group_", "nerve_feature_")


def _is_group_svg_id(name):
    return name.startswith('nerve_feature_')


def _group_number(index, size_of_digits):
    return f"{index + 1}".rjust(size_of_digits, '0')


def _analyze_elements(region, coordinate_field_name):
    fm = region.getFieldmodule()
    mesh = fm.findMeshByDimension(3)
    coordinates = fm.findFieldByName(coordinate_field_name).castFiniteElement()

    if mesh is None:
        return []

    if mesh.getSize() == 0:
        return []

    group_list = get_group_list(fm)
    group_index = 0
    grouped_path_points = {
        "ungrouped": []
    }

    size_of_digits = len(f'{len(group_list)}')
    for group in group_list:
        group_name = group.getName()
        if group_name != "marker":
            group_label = f"group_{_group_number(group_index, size_of_digits)}"
            grouped_path_points[group_label] = []
            grouped_path_points[_group_svg_id(group_label)] = group_name
        group_index += 1

    with ChangeManager(fm):
        xi_1_derivative = fm.createFieldDerivative(coordinates, 1)
        el_iterator = mesh.createElementiterator()
        element = el_iterator.next()
        while element.isValid():
            values_1 = _evaluate_field_data(element, [0, 0.5, 0.5], coordinates)
            values_2 = _evaluate_field_data(element, [1, 0.5, 0.5], coordinates)
            derivatives_1 = _evaluate_field_data(element, [0, 0.5, 0.5], xi_1_derivative)
            derivatives_2 = _evaluate_field_data(element, [1, 0.5, 0.5], xi_1_derivative)

            line_path_points = None
            if values_1 and values_2 and derivatives_1 and derivatives_2:
                line_path_points = [(values_1, derivatives_1), (values_2, derivatives_2)]

            if line_path_points is not None:
                group_index = 0
                in_group = False
                for group in group_list:
                    mesh_group = group.getMeshGroup(mesh)
                    if mesh_group.containsElement(element):
                        group_label = f"group_{_group_number(group_index, size_of_digits)}"
                        grouped_path_points[group_label].append(line_path_points)
                        in_group = True

                    group_index += 1

                if not in_group:
                    grouped_path_points["ungrouped"].append(line_path_points)

            element = el_iterator.next()

        del xi_1_derivative
        del mesh_group
        del group

    return grouped_path_points


def _evaluate_field_data(element, xi, data_field):
    mesh = element.getMesh()
    fm = mesh.getFieldmodule()
    fc = fm.createFieldcache()

    components_count = data_field.getNumberOfComponents()

    fc.setMeshLocation(element, xi)
    result, values = data_field.evaluateReal(fc, components_count)
    if result == RESULT_OK:
        return values

    return None


def _calculate_bezier_curve(pt_1, pt_2):
    h0 = pt_1[0][:2]
    v0 = pt_1[1][:2]
    h1 = pt_2[0][:2]
    v1 = pt_2[1][:2]

    b0 = h0
    b1 = add(h0, div(v0, 3))
    b2 = sub(h1, div(v1, 3))
    b3 = h1

    return b0, b1, b2, b3


def _calculate_bezier_control_points(point_data):
    bezier = {}

    for point_group in point_data:
        if point_data[point_group] and isinstance(point_data[point_group], list):
            bezier[point_group] = []
            for curve_pts in point_data[point_group]:
                bezier[point_group].append(_calculate_bezier_curve(curve_pts[0], curve_pts[1]))

    return bezier


class UnionFind:
    def __init__(self, v):
        self.parent = [-1 for _ in range(v)]

    def find(self, i):
        if self.parent[i] == -1:
            return i
        self.parent[i] = self.find(self.parent[i])  # Path compression
        return self.parent[i]

    def union(self, i, j):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j
            return root_j
        return root_i

    def __repr__(self):
        return f"{self.parent}"


def _create_key(pt):
    tolerance = 1e12
    return int(pt[0] * tolerance), int(pt[1] * tolerance)


def _connected_segments(curve):
    begin_hash = {}
    for index, c in enumerate(curve):
        key = _create_key(c[0])
        if key in begin_hash:
            print("problem repeated key!", index, c)
        begin_hash[key] = index

    curve_size = len(curve)
    uf = UnionFind(len(curve))
    for index, c in enumerate(curve):
        y_cur = _create_key(c[3])
        if y_cur in begin_hash:
            uf.union(begin_hash[y_cur], index)

    sets = {}
    for i in range(curve_size):
        root = uf.find(i)
        if root not in sets:
            sets[root] = []

        sets[root].append(i)

    segments = []
    for s in sets:
        seg = [curve[s]]
        key = _create_key(curve[s][3])
        while key in begin_hash:
            s = begin_hash[key]
            seg.append(curve[s])
            old_key = key
            key = _create_key(curve[s][3])
            if old_key == key:
                print("Breaking out of loop.")
                break
            # print(key)

        segments.append(seg)

    return segments


def _write_connected_svg_bezier_path(bezier_path, group_name):
    stroke = "grey" if group_name is None else "#01136e"

    svg = '<path d="'
    for i, bezier_section in enumerate(bezier_path):
        m_space = '' if i == 0 else ' '
        for j, b in enumerate(bezier_section):
            if j == 0:
                svg += f'{m_space}M {b[0][0]} {b[0][1]}'

            svg += f' C {b[1][0]} {b[1][1]}, {b[2][0]} {b[2][1]}, {b[3][0]} {b[3][1]}'
    svg += f'" stroke="{stroke}" fill="none"'
    svg += '/>' if group_name is None else f'><title>.centreline id({_group_svg_id(group_name)})</title></path>'

    return svg


def _write_into_svg_format(bezier_data, markers):
    svg = '<svg width="1000" height="1000" viewBox="WWW XXX YYY ZZZ" xmlns="http://www.w3.org/2000/svg">'
    for group_name in bezier_data:
        connected_paths = _connected_segments(bezier_data[group_name])

        svg += _write_connected_svg_bezier_path(connected_paths, group_name=group_name if group_name != "ungrouped" else None)

    # for i in range(len(bezier_path)):
    #     b = bezier_path[i]
    #     svg += f'<circle cx="{b[0][0]}" cy="{b[0][1]}" r="2" fill="green"/>\n'
    #     svg += f'<circle cx="{b[1][0]}" cy="{b[1][1]}" r="1" fill="yellow"/>\n'
    #     svg += f'<circle cx="{b[2][0]}" cy="{b[2][1]}" r="1" fill="purple"/>\n'
    #     svg += f'<circle cx="{b[3][0]}" cy="{b[3][1]}" r="2" fill="brown"/>\n'
    #     svg += f'<path d="M {b[0][0]} {b[0][1]} L {b[1][0]} {b[1][1]}" stroke="pink"/>\n'
    #     svg += f'<path d="M {b[3][0]} {b[3][1]} L {b[2][0]} {b[2][1]}" stroke="orange"/>\n'

    for marker in markers:
        try:
            svg += f'<circle cx="{marker[1][0]}" cy="{marker[1][1]}" r="3" fill-opacity="0.0">'
            svg += f'<title>.id({marker[0]})</title>'
            svg += '</circle>'
        except IndexError:
            print("Invalid marker for export:", marker)

    svg += '</svg>'

    return svg


def _reverse_map_annotations(csv_reader):
    reverse_map = {}
    if csv_reader:
        first = True

        for row in csv_reader:
            if first:
                first = False
            else:
                reverse_map[row[1]] = row[0]

    return reverse_map


def _label_has_annotations(entry, annotation_map):
    return entry in annotation_map and annotation_map[entry]


def _is_annotation_csv_file(csv_reader):
    """
    Check if the given CSV reader represents an annotation CSV file.

    Args:
        csv_reader (csv.reader): The CSV reader to check.

    Returns:
        bool: True if it represents an annotation CSV file, False otherwise.
    """
    if csv_reader:
        first = True

        for row in csv_reader:
            if first:
                if len(row) == 2 and row[0] == "Term ID" and row[1] == "Group name":
                    first = False
                else:
                    return False
            elif len(row) != 2:
                return False

        return True

    return False
