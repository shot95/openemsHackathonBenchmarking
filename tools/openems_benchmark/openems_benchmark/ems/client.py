from dataclasses import dataclass
from typing import Tuple, Any, List, Dict

import requests


class EmsClient:
    def __init__(self, url: str, auth: Tuple[str, str]):
        self.url = url
        self.auth = auth

    def run_simulation(self, simulation_request: Dict[str, Any]):
        response = requests.post(f"{self.url}/jsonrpc", json=simulation_request, auth=self.auth)
        response.raise_for_status()
        json_response = response.json()
        return json_response
