import json
import sys

from tabulate import tabulate

workshop_types = {
    0: "FresqueNouveauxRecits",
    1: "FresqueOceane",
    2: "FresqueBiodiversite",
    3: "FresqueNumerique",
    4: "FresqueAgriAlim",
    5: "FresqueAlimentation",
    6: "FresqueConstruction",
    7: "FresqueMobilite",
    8: "FresqueSexisme",
    9: "OGRE",
    10: "AtelierInventonsNosViesBasCarbone",
    11: "FresqueDeLeau",
    12: "FutursProches",
    13: "FresqueDiversite",
    14: "FresqueDuTextile",
    15: "FresqueDesDechets",
    16: "PuzzleClimat",
    17: "FresqueDeLaFinance",
    18: "FresqueDeLaRSE",
    100: "2tonnes",
    101: "CompteGouttes",
    102: "FresqueDuBénévolat",
    103: "FresqueDuPlastique",
    200: "FresqueClimat",
    300: "FresqueEcoCirculaire",
    500: "FresqueFrontieresPlanetaires",
    501: "HorizonsDecarbones",
    600: "2030Glorieuses",
    700: "FresqueDeLaRénovation",
    701: "FresqueDeLEnergie",
    702: "FresqueDesPossibles",
    703: "FresqueDeLaCommunication",
    704: "Zoofresque",
}


def get_json(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        logging.info(f"File not found: {file_path}")
        return 0
    except json.JSONDecodeError:
        logging.info(f"Error decoding JSON in file: {file_path}")
        return 0


def count_workshop_types(data):
    records = {}
    for record in data:
        if record["workshop_type"] in records:
            records[record["workshop_type"]] += 1
        else:
            records[record["workshop_type"]] = 1
    return records


def display_workshop_types(counts):
    for workshop_type, count in counts.items():
        logging.info(f"{workshop_types[workshop_type]}: {count} events")
    logging.info("---------")


def display_table_workshop_types(counts1, counts2):
    table = []
    for workshop_id, workshop_type in workshop_types.items():
        count1 = counts1.get(workshop_id, 0)
        count2 = counts2.get(workshop_id, 0)
        table.append([workshop_type, count1, count2, count2 - count1])
    return table


def main():
    # Check if the correct number of arguments is provided
    if len(sys.argv) != 3:
        logging.info("Usage: python program.py <file1_path> <file2_path>")
        sys.exit(1)

    # Get file paths from command-line arguments
    file1_path = sys.argv[1]
    file2_path = sys.argv[2]

    # Count entries in each file
    json1 = get_json(file1_path)
    json2 = get_json(file2_path)

    records1 = count_workshop_types(json1)
    records2 = count_workshop_types(json2)

    # display_workshop_types(records1)
    # display_workshop_types(records2)

    headers = ["Workshop", file1_path, file2_path, "Delta"]
    table = display_table_workshop_types(records1, records2)
    totals1 = sum(row[1] for row in table)
    totals2 = sum(row[2] for row in table)
    table.append(["====Totals====", totals1, totals2, totals2 - totals1])
    logging.info(tabulate(table, headers, tablefmt="fancy_grid"))


if __name__ == "__main__":
    main()
