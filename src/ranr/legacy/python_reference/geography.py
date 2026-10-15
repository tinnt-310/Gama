"""Source-vertex noding, metric routing and validation of the unchanged GIS."""

from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
import heapq
import csv
from pathlib import Path
import numpy as np
from pyproj import CRS, Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
import shapefile
from .paths import ROOT, digest, write_json


@dataclass(frozen=True)
class Station:
    name: str
    powers: tuple[float, ...]
    access_node: int
    access_distance_m: float


@dataclass
class Geography:
    stations: tuple[Station, ...]
    origin_nodes: np.ndarray
    distance_km: np.ndarray  # origin x station, road distance only
    station_distance_km: np.ndarray
    nodes: np.ndarray
    graph: csr_matrix
    validation: dict


def split_source_vertices(lines: list[list[tuple]]) -> list[list[tuple]]:
    occurrences = Counter(p for line in lines for p in set(line))
    segments = []
    for line in lines:
        if len(line) < 2:
            raise ValueError("Road with fewer than two source vertices")
        start = 0
        for index in range(1, len(line)):
            if index == len(line) - 1 or occurrences[line[index]] > 1:
                segments.append(line[start : index + 1])
                start = index
    return segments


def polygon_centroid(points: np.ndarray) -> np.ndarray:
    # Centroid under the projected metric geometry; robust fallback for zero area.
    q = np.roll(points, -1, axis=0)
    cross = points[:, 0] * q[:, 1] - q[:, 0] * points[:, 1]
    area = cross.sum()
    return (
        ((points + q) * cross[:, None]).sum(axis=0) / (3 * area)
        if abs(area) > 1e-8
        else points.mean(axis=0)
    )


def _heap_distance(graph: csr_matrix, source: int, target: int) -> float:
    best = {source: 0.0}
    pending = [(0.0, source)]
    while pending:
        cost, node = heapq.heappop(pending)
        if cost != best.get(node):
            continue
        if node == target:
            return cost
        for k in range(graph.indptr[node], graph.indptr[node + 1]):
            other = int(graph.indices[k])
            value = cost + float(graph.data[k])
            if value < best.get(other, float("inf")):
                best[other] = value
                heapq.heappush(pending, (value, other))
    return float("inf")


def load_geography(root: Path = ROOT) -> Geography:
    folder = root / "includes"
    names = ("line", "Middle", "final", "Part1", "Part2", "temporary_cs")
    hashes = {
        str(p.relative_to(root)): digest(p)
        for name in names
        for p in folder.glob(name + ".*")
    }
    for name in names:
        if not CRS.from_wkt((folder / (name + ".prj")).read_text()).equals(
            CRS.from_epsg(4326), ignore_axis_order=True
        ):
            raise ValueError(f"Unexpected CRS: {name}")
    project = Transformer.from_crs(4326, 32649, always_xy=True)
    reader = shapefile.Reader(str(folder / "line.shp"))
    lines = []
    for shape in reader.shapes():
        stops = list(shape.parts) + [len(shape.points)]
        for a, b in zip(stops, stops[1:]):
            lines.append([tuple(p[:2]) for p in shape.points[a:b]])
    segments = split_source_vertices(lines)
    coordinates = sorted(
        {line[0] for line in segments} | {line[-1] for line in segments}
    )
    ids = {p: i for i, p in enumerate(coordinates)}
    nodes = np.column_stack(project.transform(*np.asarray(coordinates).T))
    edges: dict[tuple[int, int], float] = {}
    source_length = 0.0
    noded_length = 0.0
    zero_edges = 0
    parallel_edges = 0
    for line in lines:
        xy = np.column_stack(project.transform(*np.asarray(line).T))
        source_length += float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum())
    for line in segments:
        xy = np.column_stack(project.transform(*np.asarray(line).T))
        length = float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum())
        noded_length += length
        if length <= 1e-9:
            zero_edges += 1
            continue
        u, v = ids[line[0]], ids[line[-1]]
        if (u, v) in edges:
            parallel_edges += 1
        # Sparse routing must not sum parallel road lengths.
        for key in ((u, v), (v, u)):
            edges[key] = min(length, edges.get(key, float("inf")))
    rows, cols = zip(*edges)
    graph = csr_matrix(
        (list(edges.values()), (rows, cols)), shape=(len(nodes), len(nodes))
    )
    components, labels = connected_components(graph, directed=False)
    main = np.flatnonzero(labels == np.argmax(np.bincount(labels)))
    tree = cKDTree(nodes[main])
    sites = shapefile.Reader(str(folder / "temporary_cs.shp"), encoding="utf-8")
    stations = []
    metadata_offsets = []
    for item in sites.iterShapeRecords():
        record = item.record.as_dict()
        point = np.asarray(project.transform(*item.shape.points[0][:2]))
        declared = np.asarray(
            project.transform(float(record["Longitude"]), float(record["Latitude"]))
        )
        if not np.isfinite(declared).all():
            raise ValueError("Invalid station coordinate metadata")
        metadata_offsets.append(
            {
                "station": str(record["temp_name"]),
                "geometry_attribute_distance_m": float(
                    np.linalg.norm(point - declared)
                ),
            }
        )
        distance, index = tree.query(point)
        powers = tuple(
            float(kw)
            for kw in (250, 180, 150, 60, 30, 11)
            for _ in range(int(record[f"Port_{kw}KW"]))
        )
        if not powers or any(
            float(record[f"Port_{kw}KW"]) < 0
            or int(record[f"Port_{kw}KW"]) != float(record[f"Port_{kw}KW"])
            for kw in (250, 180, 150, 60, 30, 11)
        ):
            raise ValueError("Invalid installed port count")
        stations.append(
            Station(str(record["temp_name"]), powers, int(main[index]), float(distance))
        )
    access = [s.access_node for s in stations]
    routes = dijkstra(graph, directed=False, indices=access)
    origins = []
    for name in names[1:5]:
        for shape in shapefile.Reader(str(folder / (name + ".shp"))).shapes():
            xy = np.column_stack(project.transform(*np.asarray(shape.points)[:, :2].T))
            _, nearest = tree.query(polygon_centroid(xy))
            origins.append(main[nearest])
    origins = np.asarray(origins, dtype=int)
    matrix = routes[:, access] / 1000.0
    independent_errors = [
        abs(_heap_distance(graph, access[0], target) - routes[0, target])
        for target in access
    ]
    origin_errors = [
        abs(_heap_distance(graph, access[0], int(target)) - routes[0, target])
        for target in origins[:: max(1, len(origins) // 10)]
    ]
    validations = {
        "source_hashes": hashes,
        "projection": "EPSG:32649",
        "road_direction": "bidirectional",
        "source_roads": len(reader),
        "noded_segments": len(segments),
        "nodes": len(nodes),
        "components": int(components),
        "source_length_m": source_length,
        "noded_length_m": noded_length,
        "length_error_m": abs(noded_length - source_length),
        "zero_length_segments": zero_edges,
        "parallel_segments": parallel_edges,
        "routing_parallel_policy": "minimum edge length",
        "station_count": len(stations),
        "building_count": len(origins),
        "installed_ports": sum(len(s.powers) for s in stations),
        "installed_kw": sum(sum(s.powers) for s in stations),
        "station_access": [
            {
                "name": s.name,
                "node": s.access_node,
                "distance_m": s.access_distance_m,
                "ports": len(s.powers),
                "kw": sum(s.powers),
            }
            for s in stations
        ],
        "station_coordinate_authority": "shapefile geometry, matching GAMA; DBF lat/lon retained as metadata",
        "station_metadata_offsets": metadata_offsets,
        "station_routes_km": matrix.tolist(),
        "independent_route_max_error_m": max(independent_errors + origin_errors),
        "gama_comparison": "pending reference export; independent heap routes checked",
    }
    checks = {
        "counts": len(stations) == 11 and len(origins) == 3018,
        "hardware": validations["installed_ports"] == 125
        and validations["installed_kw"] == 7195,
        "unique_stations": len({s.name for s in stations}) == 11,
        "access": all(s.access_distance_m <= 300 for s in stations),
        "length": validations["length_error_m"] < 1e-5,
        "routes": bool(np.isfinite(matrix).all())
        and bool(np.allclose(matrix, matrix.T)),
        "independent_routes": validations["independent_route_max_error_m"] < 1e-6,
        "nonzero_source": zero_edges == 0,
    }
    checks = {key: bool(value) for key, value in checks.items()}
    reference = root / "outputs/ranr/data/gama_routes.csv"
    if reference.exists():
        station_ids = {s.name: i for i, s in enumerate(stations)}
        with reference.open() as handle:
            reference_rows = list(csv.DictReader(handle))
        errors = [
            abs(
                float(row["distance_m"])
                - 1000
                * matrix[station_ids[row["origin"]], station_ids[row["destination"]]]
            )
            for row in reference_rows
        ]
        checks["gama_routes"] = bool(len(reference_rows) == 121 and max(errors) < 1e-3)
        validations["gama_comparison"] = {
            "pairs": len(errors),
            "max_error_m": float(max(errors)),
            "sha256": digest(reference),
        }
    validations.update(checks=checks, passed=all(checks.values()))
    return Geography(
        tuple(stations),
        origins,
        routes[:, origins].T / 1000.0,
        matrix,
        nodes,
        graph,
        validations,
    )


def prepare(root: Path = ROOT) -> Geography:
    geo = load_geography(root)
    write_json(root / "outputs/ranr/data/gis_validation.json", geo.validation)
    if not geo.validation["passed"]:
        raise ValueError(f"GIS validation failed: {geo.validation['checks']}")
    return geo
