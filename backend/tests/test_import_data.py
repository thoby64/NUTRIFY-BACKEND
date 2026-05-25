import os
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("SKIP_STARTUP_CHECKS", "true")
os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_URL", "postgresql://thobbs:thobby@localhost:5432/nutrition_db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import Base
from app.models.models import Food, FoodGroup, FoodNutrient, Nutrient
from import_data import DataImporter
import pandas as pd


class ImportDataTests(unittest.TestCase):
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_file.close()
        self.engine = create_engine(
            f"sqlite:///{self.db_file.name}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

        self.csv_dir = tempfile.TemporaryDirectory()
        self.csv_name = "grouped_macros.csv"
        self.csv_path = Path(self.csv_dir.name) / self.csv_name
        self.csv_path.write_text(
            "\n".join(
                [
                    "A1,Cereal and Cereal products,,,,",
                    ",Macronutrients,,ENERGY_KC,PROCNT",
                    ",,,Kcal,g",
                    "1,Bread,,250,8.5",
                    "A2,Cereal-based local dishes,,,,",
                    "2,Chapati,One recipe,300,9.0",
                    "A2,Cereal-based local dishes,,,,",
                    ",Macronutrients,FAT,CHOCDF,,",
                    ",,g,g,,",
                    "2,Chapati,\"7,8\",40,,",
                    "GM1,Miscellaneous,,,,",
                    ",Macronutrients,,ENERGY_KC,FAT",
                    ",,,Kcal,g",
                    "451,\"Beer, commercial\",,41,0.0",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.engine.dispose()
        self.csv_dir.cleanup()
        Path(self.db_file.name).unlink(missing_ok=True)

    def test_import_uses_explicit_group_rows_and_inherited_headers(self):
        with self.SessionLocal() as session:
            importer = DataImporter(self.csv_dir.name, session)
            success = importer.import_file(self.csv_name)

            self.assertTrue(success)

            groups = {group.name: group for group in session.query(FoodGroup).all()}
            self.assertIn("Cereal and Cereal products", groups)
            self.assertIn("Cereal-based local dishes", groups)
            self.assertIn("Miscellaneous", groups)

            bread = session.query(Food).filter(Food.name == "Bread").one()
            chapati = session.query(Food).filter(Food.name == "Chapati").one()
            beer = session.query(Food).filter(Food.name == "Beer, commercial").one()

            self.assertEqual(bread.food_group.name, "Cereal and Cereal products")
            self.assertEqual(chapati.food_group.name, "Cereal-based local dishes")
            self.assertEqual(beer.food_group.name, "Miscellaneous")

            energy = session.query(Nutrient).filter(Nutrient.name == "ENERGY_KC").one()
            chapati_energy = session.query(FoodNutrient).filter(
                FoodNutrient.food_id == chapati.id,
                FoodNutrient.nutrient_id == energy.id,
            ).one()
            self.assertEqual(chapati_energy.value, 300.0)

            fat = session.query(Nutrient).filter(Nutrient.name == "FAT").one()
            chapati_fat = session.query(FoodNutrient).filter(
                FoodNutrient.food_id == chapati.id,
                FoodNutrient.nutrient_id == fat.id,
            ).one()
            self.assertEqual(chapati_fat.value, 7.8)
            self.assertEqual(energy.unit, "Kcal")

    def test_import_accepts_single_letter_group_codes(self):
        single_letter_name = "single_letter_groups.csv"
        (Path(self.csv_dir.name) / single_letter_name).write_text(
            "\n".join(
                [
                    "H,Local Broths,,,,",
                    ",Macronutrients,,ENERGY_KC,PROCNT",
                    ",,,Kcal,g",
                    "853,Beef broth without oil,,44,3.9",
                    "E,Oils and fats,,,,",
                    ",Macronutrients,,ENERGY_KC,FAT",
                    ",,,Kcal,g",
                    "1103,Coconut oil,,862,100",
                ]
            ),
            encoding="utf-8",
        )

        with self.SessionLocal() as session:
            importer = DataImporter(self.csv_dir.name, session)
            success = importer.import_file(single_letter_name)

            self.assertTrue(success)

            broths = session.query(FoodGroup).filter(FoodGroup.name == "Local Broths").one()
            oils = session.query(FoodGroup).filter(FoodGroup.name == "Oils and fats").one()
            self.assertIsNotNone(broths)
            self.assertIsNotNone(oils)

            broth_food = session.query(Food).filter(Food.name == "Beef broth without oil").one()
            oil_food = session.query(Food).filter(Food.name == "Coconut oil").one()
            self.assertEqual(broth_food.food_group_id, broths.id)
            self.assertEqual(oil_food.food_group_id, oils.id)

    def test_parser_skips_vitamin_unit_rows_and_classifies_fat_profile_headers(self):
        rows = [
            ["H", "Local Broths", "", "", "", ""],
            ["", "Vitamins", "VITA", "A_VITA", "VITD", "VITE"],
            ["", "", "µ g RE", "µ g RE", "µ g", "µ g"],
            ["", "Macronutrients", "FASAT", "FAMS", "FAPU", "CHOLE"],
            ["", "", "g", "g", "g", "mg"],
        ]
        df = pd.DataFrame(rows)
        importer = DataImporter(self.csv_dir.name, None)

        vitamin_header = importer.parse_header_definition(df, 1)
        vitamin_units = importer.parse_header_definition(df, 2)
        fat_profile_header = importer.parse_header_definition(df, 3)
        fat_profile_units = importer.parse_header_definition(df, 4)

        self.assertIsNotNone(vitamin_header)
        self.assertIsNone(vitamin_units)
        self.assertEqual(vitamin_header["nutrient_type_name"], "vitamins")
        self.assertIsNotNone(fat_profile_header)
        self.assertIsNone(fat_profile_units)
        self.assertEqual(fat_profile_header["nutrient_type_name"], "macronutrients")


if __name__ == "__main__":
    unittest.main()
