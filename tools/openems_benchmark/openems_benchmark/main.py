import argparse
import os

from openems_benchmark.ems.client import EmsClient
from openems_benchmark import inout
from openems_benchmark import cost_function


def main():
    dir_path = os.path.dirname(os.path.abspath(__file__))

    parser = argparse.ArgumentParser(
        "OpenEMS Benchmarking", description="Tool to execute benchmarks against a running OpenEMS System"
    )
    parser.add_argument("--openems_url", default="http://localhost:8084", help="URL to the OpenEMS REST service")
    parser.add_argument("--openems_user", default="admin", help="User for the OpenEMS Rest API")
    parser.add_argument(
        "--openems_password",
        default="admin",
        help="Password for the OpenEMS Rest API. You can also set this via the environment variable OPENEMS_PASSWORD",
    )
    parser.add_argument("--openems_config", default="component_config.json", help="Path of JSON config file")
    parser.add_argument(
        "--energy_consumption",
        default="load_profile.txt",
        help="Path of energy consumption .txt file",
    )
    parser.add_argument(
        "--energy_production",
        default="generation_profile.txt",
        help="Path of energy production .txt file",
    )
    parser.add_argument(
        "--simulation_output",
        default="output.csv",
        help="Path of the output CSV file with simulation results",
    )
    parser.add_argument(
        "--result_to_excel",
        action="store_true",
        help="Option to additionally extract results in an Excel sheet",
    )
    parser.add_argument(
        "--system_cost",
        default="grid_prices.json",
        help="Path to JSON grid price file",
    )

    parser.add_argument(
        "--degradation_active",
        action="store_true",
        help="Option to calculate BESS degradation",
    )
    args = parser.parse_args()

    openems_password = args.openems_password if args.openems_password else os.getenv("OPENEMS_PASSWORD")

    simulation_request = inout.load_openems_configuration(
        openems_config_file=args.openems_config,
        energy_consumption_file=args.energy_consumption,
        energy_production_file=args.energy_production,
    )

    ems_cli = EmsClient(url=args.openems_url, auth=(args.openems_user, openems_password))
    simulation_response = ems_cli.run_simulation(simulation_request=simulation_request)

    result_dict = cost_function._run_reward_function(
        simulation_response, args.openems_config, args.system_cost, args.degradation_active
    )

    inout.results_to_csv(result_dict, output_file=args.simulation_output, to_Excel=args.result_to_excel)
    print("Simulation results saved to:", args.simulation_output)


# Press the green button in the gutter to run the script.
if __name__ == "__main__":
    main()
