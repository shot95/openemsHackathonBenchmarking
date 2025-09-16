from typing import Any, Dict

import numpy as np
import pandas as pd
import os
import json
import math


def _replace_active_power(
    openems_simulation_config: Dict[str, Any], energy_consumption_file: str, energy_production_file: str
) -> Dict[str, Any] or str:
    def _replace(meter_name: str, file_path: str) -> Dict[str, Any]:
        if meter_name in openems_simulation_config["params"]["payload"]["params"]["profiles"]:
            try:
                data = np.loadtxt(fname=file_path)
            except ValueError:
                # try again with comma delimiter
                data = np.loadtxt(fname=file_path, delimiter=",")
            openems_simulation_config["params"]["payload"]["params"]["profiles"][meter_name] = data.tolist()

    # adding load profile to json
    _replace("meter1/ActivePower", energy_consumption_file)

    # adding generation profile to json
    _replace("meter2/ActivePower", energy_production_file)

    return openems_simulation_config


def load_openems_configuration(
    openems_config_file: str, energy_consumption_file: str, energy_production_file: str
) -> Dict[str, Any]:
    with open(openems_config_file, "r") as f:
        data = json.load(f)
    _replace_active_power(data, energy_consumption_file, energy_production_file)
    return data


def results_to_csv(result: pd.DataFrame, output_file: str, to_Excel: bool):

    result.to_csv(output_file, index=False)

    if to_Excel == True:
        output_excel = output_file.replace(".csv", ".xlsx")
        result.to_excel(output_excel, index=False)
