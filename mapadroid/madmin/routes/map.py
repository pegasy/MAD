import json
from typing import List, Optional

from flask import jsonify, render_template, request
from flask_caching import Cache

from mapadroid.db.DbWrapper import DbWrapper
from mapadroid.geofence.geofenceHelper import GeofenceHelper
from mapadroid.madmin.functions import (auth_required,
                                        generate_coords_from_geofence,
                                        get_bound_params, get_coord_float,
                                        get_geofences)
from mapadroid.route.RouteManagerBase import RoutePoolEntry
from mapadroid.utils import MappingManager
from mapadroid.utils.collections import Location
from mapadroid.utils.language import get_mon_name
from mapadroid.utils.logging import LoggerEnums, get_logger
from mapadroid.utils.questGen import QuestGen
from mapadroid.utils.s2Helper import S2Helper

logger = get_logger(LoggerEnums.madmin)
cache = Cache(config={'CACHE_TYPE': 'simple'})


class MADminMap:
    def __init__(self, db: DbWrapper, args, mapping_manager: MappingManager, app, data_manager, quest_gen: QuestGen):
        self._quest_gen = quest_gen
        self._db: DbWrapper = db
        self._args = args
        self._app = app
        if self._args.madmin_time == "12":
            self._datetimeformat = '%Y-%m-%d %I:%M:%S %p'
        else:
            self._datetimeformat = '%Y-%m-%d %H:%M:%S'

        self._mapping_manager: MappingManager = mapping_manager
        self._data_manager = data_manager

        cache.init_app(self._app)

    def add_route(self):
        routes = [
            ("/map", self.map),
            ("/get_workers", self.get_workers),
            ("/get_geofences", self.get_geofences),
            ("/get_areas", self.get_areas),
            ("/get_route", self.get_route),
            ("/get_prioroute", self.get_prioroute),
            ("/get_spawns", self.get_spawns),
            ("/get_gymcoords", self.get_gymcoords),
            ("/get_quests", self.get_quests),
            ("/get_map_mons", self.get_map_mons),
            ("/get_cells", self.get_cells),
            ("/get_stops", self.get_stops)
        ]
        for route, view_func in routes:
            self._app.route(route)(view_func)

    def start_modul(self):
        self.add_route()

    @auth_required
    def map(self):
        setlat = request.args.get('lat', 0)
        setlng = request.args.get('lng', 0)
        return render_template('map.html', lat=self._args.home_lat, lng=self._args.home_lng,
                               setlat=setlat, setlng=setlng)

    @auth_required
    def get_workers(self):
        positions = []
        devicemappings = self._mapping_manager.get_all_devicemappings()
        for name, values in devicemappings.items():
            lat = values.get("settings").get("last_location", Location(0.0, 0.0)).lat
            lon = values.get("settings").get("last_location", Location(0.0, 0.0)).lng

            worker = {
                "name": str(name),
                "lat": get_coord_float(lat),
                "lon": get_coord_float(lon)
            }
            positions.append(worker)

        return jsonify(positions)

    @auth_required
    def get_geofences(self):
        geofences = self._data_manager.get_root_resource("geofence")
        export = []

        for geofence_id, geofence in geofences.items():
            geofence_helper = GeofenceHelper(geofence, None, geofence["name"])
            if len(geofence_helper.geofenced_areas) == 1:
                geofenced_area = geofence_helper.geofenced_areas[0]
                if "polygon" in geofenced_area:
                    export.append({
                        "id": geofence_id,
                        "name": geofence["name"],
                        "coordinates": geofenced_area["polygon"]
                    })

        return jsonify(export)

    @auth_required
    def get_areas(self):
        areas = self._mapping_manager.get_areas()
        areas_sorted = sorted(areas, key=lambda x: areas[x]['name'])
        geofences = get_geofences(self._mapping_manager, self._data_manager)
        geofencexport = []
        for area_id in areas_sorted:
            fences = geofences[area_id]
            coordinates = []
            for fname, coords in fences.get('include').items():
                coordinates.append([coords, fences.get('exclude').get(fname, [])])
            geofencexport.append({'name': areas[area_id]['name'], 'coordinates': coordinates})
        return jsonify(geofencexport)

    @auth_required
    def get_route(self):
        routeinfo_by_id = {}
        routemanager_names = self._mapping_manager.get_all_routemanager_names()

        for routemanager in routemanager_names:
            (memory_route, workers) = self._mapping_manager.routemanager_get_current_route(routemanager)
            if memory_route is None:
                continue

            mode = self._mapping_manager.routemanager_get_mode(routemanager)
            name = self._mapping_manager.routemanager_get_name(routemanager)
            routecalc_id = self._mapping_manager.routemanager_get_routecalc_id(routemanager)
            routeinfo_by_id[routecalc_id] = routeinfo = {
                "id": routecalc_id,
                "route": memory_route,
                "name": name,
                "mode": mode,
                "subroutes": []
            }

            if len(workers) > 1:
                for worker, worker_route in workers.items():
                    routeinfo["subroutes"].append({
                        "id": "%d_sub_%s" % (routecalc_id, worker),
                        "route": worker_route,
                        "name": "%s - %s" % (routeinfo["name"], worker),
                        "tag": "subroute"
                    })

        if len(routeinfo_by_id) > 0:
            routecalcs = self._data_manager.get_root_resource("routecalc")
            for routecalc_id, routecalc in routecalcs.items():
                if routecalc_id in routeinfo_by_id:
                    routeinfo = routeinfo_by_id[routecalc_id]
                    db_route = list(map(lambda coord: Location(coord["lat"], coord["lng"]),
                                        routecalc.get_saved_json_route()))
                    if db_route != routeinfo["route"]:
                        routeinfo["subroutes"].append({
                            "id": "%d_unapplied" % routeinfo["id"],
                            "route": db_route,
                            "name": "%s (unapplied)" % routeinfo["name"],
                            "tag": "unapplied"
                        })

        return jsonify(list(map(lambda route: get_routepool_route(route), routeinfo_by_id.values())))

    @auth_required
    def get_prioroute(self):
        routeexport = []

        routemanager_names = self._mapping_manager.get_all_routemanager_names()

        for routemanager in routemanager_names:
            mode = self._mapping_manager.routemanager_get_mode(routemanager)
            name = self._mapping_manager.routemanager_get_name(routemanager)
            route: Optional[List[Location]] = self._mapping_manager.routemanager_get_current_prioroute(
                routemanager)

            if route is None:
                continue
            route_serialized = []

            for location in route:
                route_serialized.append({
                    "timestamp": location[0],
                    "latitude": get_coord_float(location[1].lat),
                    "longitude": get_coord_float(location[1].lng)
                })

            routeexport.append({
                "name": name,
                "mode": mode,
                "coordinates": route_serialized
            })

        return jsonify(routeexport)

    @auth_required
    def get_spawns(self):
        ne_lat, ne_lon, sw_lat, sw_lon, o_ne_lat, o_ne_lon, o_sw_lat, o_sw_lon = get_bound_params(request)
        timestamp = request.args.get("timestamp", None)

        coords = {}
        data = json.loads(
            self._db.download_spawns(
                ne_lat,
                ne_lon,
                sw_lat,
                sw_lon,
                o_ne_lat=o_ne_lat,
                o_ne_lon=o_ne_lon,
                o_sw_lat=o_sw_lat,
                o_sw_lon=o_sw_lon,
                timestamp=timestamp
            )
        )

        for spawnid in data:
            spawn = data[str(spawnid)]
            if spawn["event"] not in coords:
                coords[spawn["event"]] = []
            coords[spawn["event"]].append({
                "id": spawn["id"],
                "endtime": spawn["endtime"],
                "lat": spawn["lat"],
                "lon": spawn["lon"],
                "spawndef": spawn["spawndef"],
                "lastnonscan": spawn["lastnonscan"],
                "lastscan": spawn["lastscan"],
                "first_detection": spawn["first_detection"],
                "event": spawn["event"]
            })

        cluster_spawns = []
        for spawn in coords:
            cluster_spawns.append({"EVENT": spawn, "Coords": coords[spawn]})

        return jsonify(cluster_spawns)

    @auth_required
    def get_gymcoords(self):
        ne_lat, ne_lon, sw_lat, sw_lon, o_ne_lat, o_ne_lon, o_sw_lat, o_sw_lon = get_bound_params(request)
        timestamp = request.args.get("timestamp", None)

        coords = []

        data = self._db.get_gyms_in_rectangle(
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            o_ne_lat=o_ne_lat,
            o_ne_lon=o_ne_lon,
            o_sw_lat=o_sw_lat,
            o_sw_lon=o_sw_lon,
            timestamp=timestamp
        )

        for gymid in data:
            gym = data[str(gymid)]

            coords.append({
                "id": gymid,
                "name": gym["name"],
                "img": gym["url"],
                "lat": gym["latitude"],
                "lon": gym["longitude"],
                "team_id": gym["team_id"],
                "last_updated": gym["last_updated"],
                "last_scanned": gym["last_scanned"],
                "raid": gym["raid"]
            })

        return jsonify(coords)

    @auth_required
    def get_quests(self):
        coords = []

        fence = request.args.get("fence", None)
        if fence not in (None, 'None', 'All'):
            fence = generate_coords_from_geofence(self._mapping_manager, self._data_manager, fence)
        else:
            fence = None

        ne_lat, ne_lon, sw_lat, sw_lon, o_ne_lat, o_ne_lon, o_sw_lat, o_sw_lon = get_bound_params(request)
        timestamp = request.args.get("timestamp", None)

        data = self._db.quests_from_db(
            ne_lat=ne_lat,
            ne_lon=ne_lon,
            sw_lat=sw_lat,
            sw_lon=sw_lon,
            o_ne_lat=o_ne_lat,
            o_ne_lon=o_ne_lon,
            o_sw_lat=o_sw_lat,
            o_sw_lon=o_sw_lon,
            timestamp=timestamp,
            fence=fence
        )

        for stopid in data:
            quest = data[str(stopid)]
            coords.append(self._quest_gen.generate_quest(quest))

        return jsonify(coords)

    @auth_required
    def get_map_mons(self):
        ne_lat, ne_lon, sw_lat, sw_lon, o_ne_lat, o_ne_lon, o_sw_lat, o_sw_lon = get_bound_params(request)
        timestamp = request.args.get("timestamp", None)

        data = self._db.get_mons_in_rectangle(
            ne_lat=ne_lat,
            ne_lon=ne_lon,
            sw_lat=sw_lat,
            sw_lon=sw_lon,
            o_ne_lat=o_ne_lat,
            o_ne_lon=o_ne_lon,
            o_sw_lat=o_sw_lat,
            o_sw_lon=o_sw_lon,
            timestamp=timestamp
        )

        mons_raw = {}

        for index, _ in enumerate(data):
            try:
                mon_id = data[index]["mon_id"]
                if str(mon_id) in mons_raw:
                    mon_raw = mons_raw[str(mon_id)]
                else:
                    mon_raw = get_mon_name(mon_id)
                    mons_raw[str(mon_id)] = mon_raw

                data[index]["encounter_id"] = str(data[index]["encounter_id"])
                data[index]["name"] = mon_raw
            except Exception:
                pass

        return jsonify(data)

    @auth_required
    def get_cells(self):
        ne_lat, ne_lon, sw_lat, sw_lon, o_ne_lat, o_ne_lon, o_sw_lat, o_sw_lon = get_bound_params(request)
        timestamp = request.args.get("timestamp", None)

        data = self._db.get_cells_in_rectangle(
            ne_lat=ne_lat,
            ne_lon=ne_lon,
            sw_lat=sw_lat,
            sw_lon=sw_lon,
            o_ne_lat=o_ne_lat,
            o_ne_lon=o_ne_lon,
            o_sw_lat=o_sw_lat,
            o_sw_lon=o_sw_lon,
            timestamp=timestamp
        )

        ret = []
        for cell in data:
            ret.append({
                "id": str(cell["cell_id"]),
                "polygon": S2Helper.coords_of_cell(cell["cell_id"]),
                "updated": cell["updated"]
            })

        return jsonify(ret)

    @auth_required
    def get_stops(self):
        ne_lat, ne_lon, sw_lat, sw_lon, o_ne_lat, o_ne_lon, o_sw_lat, o_sw_lon = get_bound_params(request)
        data = self._db.get_stops_in_rectangle(
            ne_lat,
            ne_lon,
            sw_lat,
            sw_lon,
            o_ne_lat=o_ne_lat,
            o_ne_lon=o_ne_lon,
            o_sw_lat=o_sw_lat,
            o_sw_lon=o_sw_lon,
            timestamp=request.args.get("timestamp", None)
        )
        return jsonify(data)


def get_routepool_route(route):
    return {
        "id": route["id"],
        "name": route["name"],
        "mode": route["mode"],
        "coordinates": get_routepool_coords(route["route"]),
        "subroutes": list(map(lambda subroute: {
            "id": subroute["id"],
            "name": subroute["name"],
            "tag": subroute["tag"],
            "coordinates": get_routepool_coords(subroute["route"])
        }, route["subroutes"]))
    }


def get_routepool_coords(coord_list):
    route_serialized = []
    prepared_coords = coord_list
    if isinstance(coord_list, RoutePoolEntry):
        prepared_coords = coord_list.subroute
    for location in prepared_coords:
        route_serialized.append([get_coord_float(location.lat), get_coord_float(location.lng)])
    return route_serialized
