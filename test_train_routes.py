import unittest
import time
import datetime
from unittest.mock import patch

import alerts
import server


class TrainRouteApiTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_train_search_returns_timetable_identity(self):
        response = self.client.get("/api/trains?q=12680")
        self.assertEqual(response.status_code, 200)
        train = next(item for item in response.json["trains"] if item["number"] == "12680")
        self.assertEqual(train["name"], "CHENNAI EXPRESS")
        self.assertEqual(train["source"], "COIMBATORE JN")
        self.assertEqual(train["destination"], "CHENNAI CENTRAL")

    def test_route_returns_ordered_stops_with_coordinates(self):
        server.ROUTE_CACHE.pop("12680", None)
        with patch.object(
            server,
            "_geocode_station",
            side_effect=lambda name: {
                "lat": 11.0 + len(name) / 1000,
                "lon": 77.0 + len(name) / 1000,
                "source": "test",
            },
        ):
            response = self.client.get("/api/trains/12680/route")

        self.assertEqual(response.status_code, 200)
        route = response.json
        self.assertEqual(route["train"]["name"], "CHENNAI EXPRESS")
        self.assertEqual(len(route["stops"]), 14)
        self.assertEqual(route["stops"][0]["code"], "CBE")
        self.assertEqual(route["stops"][-1]["code"], "MAS")
        self.assertTrue(all("lat" in stop and "lon" in stop for stop in route["stops"]))

    def test_unknown_train_route_returns_not_found(self):
        response = self.client.get("/api/trains/999999/route")
        self.assertEqual(response.status_code, 404)

    def test_alert_message_uses_mapped_route_station_and_train(self):
        route = {
            "stops": [
                {"name": "START", "lat": 11.0, "lon": 77.0, "distance_km": 0.0},
                {"name": "END", "lat": 11.0, "lon": 78.0, "distance_km": 100.0},
            ],
        }
        loc = {
            "lat": 11.0,
            "lon": 77.5,
            "train": {"number": "12680", "name": "CHENNAI EXPRESS"},
            **server._route_location(route, 11.0, 77.5),
        }
        previous_alert_time = server.ENGINE.last_alert
        captured = {}

        def fake_send(messages):
            captured["messages"] = messages
            return []

        try:
            with patch("engine.alerts.send_all", side_effect=fake_send):
                result = server.ENGINE.handle_external(
                    "push_fall", time.time() + 100, 80, loc, "ALERT", 1
                )
        finally:
            server.ENGINE.last_alert = previous_alert_time

        self.assertTrue(result["sent"])
        self.assertAlmostEqual(result["ctx"]["km"], server.haversine(11.0, 77.5, 11.0, 77.0))
        self.assertEqual(result["ctx"]["prev"], "START")
        self.assertEqual(result["ctx"]["next"], "END")
        message = captured["messages"]["guard"][1]
        self.assertIn("Train 12680 (CHENNAI EXPRESS)", message)
        self.assertIn("Nearest timetable station: START (54.6 km away)", message)
        self.assertIn("Approximate route segment: START to END", message)

    def test_alert_uses_selected_timetable_train(self):
        captured = {}
        train_number = next(
            number for number, _ in server.TRAIN_GROUPS
            if number != server.CFG["train"]["number"]
        )
        selected_train = server._train_for_number(train_number)
        original_route = server.ROUTE_CACHE.get(train_number)
        server.ROUTE_CACHE[train_number] = {
            "stops": [
                {"name": "START", "lat": 11.0, "lon": 77.0, "distance_km": 0.0},
                {"name": "END", "lat": 11.0, "lon": 78.0, "distance_km": 100.0},
            ],
        }

        def fake_handle(*args):
            captured["location"] = args[3]
            return {"sent": True, "reason": "test", "results": []}

        try:
            with patch.object(server.ENGINE, "handle_external", side_effect=fake_handle):
                response = self.client.post("/api/alert", json={
                    "event": "PUSH",
                    "speed": 80,
                    "loc": {"lat": 11.0, "lon": 77.5},
                    "stage": "ALERT",
                    "persons": 2,
                    "train_number": train_number,
                })
        finally:
            if original_route is None:
                server.ROUTE_CACHE.pop(train_number, None)
            else:
                server.ROUTE_CACHE[train_number] = original_route

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["location"]["train"]["number"], train_number)
        self.assertEqual(captured["location"]["train"]["name"], selected_train["name"])
        self.assertEqual(captured["location"]["train"]["coach"], "")
        self.assertEqual(captured["location"]["segment"], "START -> END")
        self.assertAlmostEqual(captured["location"]["km"], 50.0)
        self.assertEqual(captured["location"]["nearest_station"]["name"], "START")

    def test_alert_does_not_reuse_default_coach_for_another_train(self):
        alert_config = dict(server.CFG)
        alert_config["train"] = {
            **server.CFG["train"],
            "number": "99999",
            "name": "OTHER TRAIN",
            "coach": "",
        }
        context = {
            "person_count": 1,
            "time": datetime.datetime(2025, 1, 1, 12, 0, 0),
            "lat": 11.0,
            "lon": 77.0,
            "accuracy": None,
            "speed": 80,
            "km": 0,
        }
        messages = alerts.build(
            "fall", context, alert_config, {"name": "START"}
        )

        self.assertIn("Train 99999 (OTHER TRAIN)", messages["guard"][1])
        self.assertNotIn("coach", messages["guard"][1])


if __name__ == "__main__":
    unittest.main()
