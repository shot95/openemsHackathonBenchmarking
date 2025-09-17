from typing import Any, Dict
import pandas as pd
import numpy as np
import json
import math
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
from dateutil.relativedelta import relativedelta


@dataclass
class SimulationCostResult:
    peak_power_cost: float
    grid_buying_cost: float
    grid_selling_revenue: float
    total_system_cost: float
    degradation_cost: Optional[float] = None


def _run_reward_function(
    json_response: Dict[str, Any],
    ess_config_file: str,
    path_cost_list_json: str,
    degradation_active: bool,
):
    def _simulation_response_to_dataframe(result):
        result = pd.DataFrame()

        for key in json_response["result"]["data"]:
            array = np.array(json_response["result"]["data"][key])
            result[key] = array

        result = result.apply(pd.to_numeric, errors="coerce")

        return result

    def finding_peak_power(df: pd.DataFrame):

        max_power = df["_sum/GridActivePower"].max()

        return max_power

    def calculating_LSK_costs(power: float, cost: float):
        """
        power -> kW
        cost  -> €/kW
        """

        return power * cost

    def calculating_grid_usage_costs(
        energy_from_grid: float,
        energy_to_grid: float,
        from_grid_cost: float,
        to_grid_cost: float,
    ):

        grid_buying = energy_from_grid * from_grid_cost
        grid_selling = energy_to_grid * to_grid_cost

        return grid_buying, grid_selling

    def getting_full_load_hours(yearly_consumption, yearly_peak):

        return yearly_consumption / yearly_peak

    def grid_usage_costs(path_cost_list: str, full_load: float):
        """
        GridBuyingPrice     [€/kWh]: The fixed grid usage cost per kWh

        GridSellingPrice    [€/kWh]: The fixed grid feed-in revenue of the solar panels

        PeakPowerPrice      [€/kW]:  The yearly high power demand costs of using the grid
        """

        with open(path_cost_list, "r") as f:
            cost_list = json.load(f)

        if full_load >= 2500:
            prices = cost_list["GridBuyingPrice"]["Above_2500h"]
        else:
            prices = cost_list["GridBuyingPrice"]["Below_2500"]

        if cost_list["LoadProfileUnits"] == "W":
            prices["GridUsagePrice"] = (
                prices["GridUsagePrice"] / 1000
            )  # €/kWh = (€/kWh) * (kWh/1000Wh)
            cost_list["GridSellingPrice"] = cost_list["GridSellingPrice"] / 1000
            prices["PeakPowerPrice"] = prices["PeakPowerPrice"] / 1000
        elif cost_list["LoadProfileUnits"] == "kW":
            pass
        elif cost_list["LoadProfileUnits"] == "MW":
            prices["GridUsagePrice"] = (
                prices["GridUsagePrice"] * 1000
            )  # €/kWh = (€/kWh) * (1000kWh/MWh)
            cost_list["GridSellingPrice"] = cost_list["GridSellingPrice"] * 1000
            prices["PeakPowerPrice"] = prices["PeakPowerPrice"] * 1000

        return (
            prices["GridUsagePrice"],
            cost_list["GridSellingPrice"],
            prices["PeakPowerPrice"],
            cost_list["LoadProfileUnits"],
        )

    def degradation_model(df, ess_config):
        """
        _sum/EssSoc:    BESS percentage state of charge (0% -> 100%)

        SoC:            BESS state of charge (0 -> 1)

        SoC_energy:     BESS energy content (Wh/kWh/MWH units are the same as the units in the consumption and production profiles)

        initialSoc:     BESS initial SoC (between 0 and 100) entered by user

        """
        # load config file
        with open(ess_config, "r") as f:
            ess_config_data = json.load(f)

        # Navigate to the components list
        components = ess_config_data["params"]["payload"]["params"]["components"]

        # Find the component with the desired factoryPid
        for component in components:
            if component["factoryPid"] == "Simulator.EssSymmetric.Reacting":
                for prop in component["properties"]:
                    if prop["name"] == "capacity":
                        capacity_value = prop["value"]
                    elif prop["name"] == "initialSoc":
                        initial_soc = prop["value"]

        # BESS Capacity
        BESS_capacity = capacity_value

        # BESS initial Capacity
        BESS_inital_capacity = BESS_capacity * (
            initial_soc / 100
        )  # have to multiply by initial_soc for the cases where the battery initially not full is

        # calculating SoC
        df["SoC_energy"] = df["_sum/EssSoc"] * BESS_capacity
        df["SoC"] = df["_sum/EssSoc"] / 100

        # depth of discharge (DoD) stress  coefficients
        k_DoD_1 = 1.4 * math.pow(10, 5)
        k_DoD_2 = -0.5
        k_DoD_3 = -1.23 * math.pow(10, 5)

        # time(t) stress coefficients
        k_t = 1.75 * math.pow(10, -10)

        # state of charge (SoC) stress coefficients
        k_SoC = 2.62

        # temperature stress coefficients
        k_T = 4.46 * math.pow(10, -2)

        # temperature
        T_ref = 273  # °K
        T = 298  # °K

        # calculating DoD
        DoD = []
        DoD.append(
            0
        )  # appending initial value (at first timestep no discharged energy)
        for n in range(len(df["SoC_energy"])):
            try:
                DoD.append(abs((df["SoC"][n + 1] - df["SoC"][n])))
            except:
                pass
        df["DoD"] = DoD

        # Stress Models
        df["s_T"] = np.exp(
            k_T * (T - T_ref) * (T_ref / T)
        )  # Temperature Stress Model equation

        df["s_t"] = (
            k_t * 900
        )  # Time Stress Model (900 sec for 15min timestep intervals) equation

        df["s_SoC"] = np.exp(k_SoC * ((df["SoC"]) - 0.3))  # SoC Stress Model equation

        df["s_DoD"] = np.pow(
            np.pow(df["DoD"], k_DoD_2) * k_DoD_1 + k_DoD_3, -1
        )  # DoD Stress Model equation

        # degradation function
        f_d = (df["s_DoD"] + df["s_t"]) * df["s_SoC"] * df["s_T"]

        # Battery Life
        L = []
        L_initial = 0.2
        L.append(L_initial)

        for n in range(len(df) - 1):
            L.append(1 - (1 - L[n]) * math.exp(-f_d[n + 1]))

        df["Battery_Life"] = L
        df["SoH"] = 1 - df["Battery_Life"]

        # calculating remaining max. capacity after degradation
        max_capa = []
        max_capa.append(BESS_capacity)  # initially no degradation
        for n in range(len(df) - 1):
            max_capa.append(max_capa[n] * (1 - df["SoH"][n] + df["SoH"][n + 1]))
        df["BESS_max_capacity_degradation"] = max_capa

        return df

    def calculating_degradation_cost(df, costs_file):
        """
        BatteryUnitPrice: The price of BESS per kWh (total price/total capacity)

        LoadProfileUnits: The units of the load profiles provided by the user (W/kW/MW)

        """
        # load costs file
        with open(costs_file, "r") as f:
            costs = json.load(f)

        battery_cost_kwh = costs["BatteryUnitPrice"]  # €/kWh
        profile_unit = costs["LoadProfileUnits"]

        if profile_unit == "W":
            battery_cost_kwh = battery_cost_kwh / 1000  # €/kWh = (€/kWh) * (kWh/1000Wh)
        elif profile_unit == "kW":
            battery_cost_kwh = battery_cost_kwh  # same unit
        elif profile_unit == "MW":
            battery_cost_kwh = (
                battery_cost_kwh * 1000
            )  # €/kWh = (€/kWh) * (1000kWh/MWh)

        degradation_cost = []
        degradation_cost.append(0)  # initially no degradation costs

        for n in range(len(df) - 1):
            degradation_cost.append(
                (
                    df["BESS_max_capacity_degradation"][n]
                    - df["BESS_max_capacity_degradation"][n + 1]
                )
                * battery_cost_kwh
            )
        df["degradation_cost"] = degradation_cost

        return sum(df["degradation_cost"])

    def _total_Energy_FromToGrid(df):
        power_from_grid = []
        power_to_grid = []

        for value in df:
            if value > 0:
                power_from_grid.append(value)
            elif value < 0:
                power_to_grid.append(value)
        total_from_grid = (
            sum(power_from_grid) / 4
        )  # divided by 4 since timestep = 15minutes
        total_to_grid = (
            sum(power_to_grid) / 4
        )  # divided by 4 since timestep = 15minutes

        return total_from_grid, total_to_grid

    result_dict = _simulation_response_to_dataframe(json_response)

    # Finding peak power
    power_max = finding_peak_power(result_dict)

    # Total Energy Exchanged with Grid
    energy_from_grid, energy_to_grid = _total_Energy_FromToGrid(
        result_dict["_sum/GridActivePower"]
    )

    # checking if the input time provided is at least one year

    # Finding full load hours to get correct grid prices
    full_load_hours = getting_full_load_hours(energy_from_grid, power_max)

    # getting grid usage cost according to actual power use
    grid_usage_price, grid_selling_price, peak_power_price, input_power_unit = (
        grid_usage_costs(path_cost_list_json, full_load_hours)
    )
    energyUnit = input_power_unit + "h"

    # calculating grid usage costs
    buying, selling = calculating_grid_usage_costs(
        energy_from_grid, energy_to_grid, grid_usage_price, grid_selling_price
    )

    # calculating Peak Power costs
    peak_power_cost = calculating_LSK_costs(power_max, peak_power_price)

    if degradation_active:
        # running degradation model
        result_dict = degradation_model(result_dict, ess_config_file)

        # calculating degradation costs (BESS operational costs)
        degradation_cost = calculating_degradation_cost(
            result_dict, path_cost_list_json
        )

        total_system_cost = peak_power_cost + buying + degradation_cost - selling

    else:
        total_system_cost = peak_power_cost + buying - selling

    with open(ess_config_file, "r") as f:
        ess_config = json.load(f)
    simStartTime = datetime.strptime(
        ess_config["params"]["payload"]["params"]["clock"]["start"],
        "%Y-%m-%dT%H:%M:%S.%fZ",
    )
    simEndTime = datetime.strptime(
        ess_config["params"]["payload"]["params"]["clock"]["end"],
        "%Y-%m-%dT%H:%M:%S.%fZ",
    )
    is_one_year = (
        relativedelta(simEndTime, simStartTime).years == 1
        and relativedelta(simEndTime, simStartTime).months == 0
        and relativedelta(simEndTime, simStartTime).days == 0
    )

    print("--------------------------------------------------------")
    print("The simulated system has the following costs:")

    print(f"Total energy bought from gird: {energy_from_grid} {input_power_unit }h")
    print(f"Total energy sold to grid: {energy_to_grid} {input_power_unit}h")
    if is_one_year:
        print(f"Peak power cost: {peak_power_cost} EUR")
    else:
        print(
            f"Unable to calculate the Peak power cost. Simulate exactly one year to be able to calculate this value correctly"
        )
    if degradation_active:
        print(f"BESS degradation cost: {degradation_cost} EUR")
    if is_one_year:
        print(f"Total cost: {total_system_cost} EUR")
    else:
        print(
            f"Unable to calculate the Total system cost, since the peak power cost could not be properly estimated."
        )

    print("--------------------------------------------------------")

    result = SimulationCostResult(
        peak_power_cost=peak_power_cost,
        grid_buying_cost=buying,
        grid_selling_revenue=selling,
        total_system_cost=total_system_cost,
        degradation_cost=degradation_cost if degradation_active else None,
    )
    # result_dict["system costs"] = result
    result_dict["peak_power_cost"] = peak_power_cost
    result_dict["grid_buying_cost"] = buying
    result_dict["grid_selling_revenue"] = selling
    result_dict["total_system_cost"] = total_system_cost
    result_dict["degradation_cost"] = degradation_cost if degradation_active else None

    return result_dict
