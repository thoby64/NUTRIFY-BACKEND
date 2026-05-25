#!/usr/bin/env python3
"""
Import nutrition data from CSV files into PostgreSQL database

IMPORTANT: This importer requires CSV format files ONLY.
Before importing, convert your Excel files to CSV format:
1. Open the Excel file in LibreOffice Calc or Excel
2. Select all data (Ctrl+A)
3. File → Export As → CSV
4. Save with .csv extension in the same directory

Supported CSV files:
  - amincereals_090405.csv
  - macrocereals_091101.csv
  - mineralscereals_091101.csv
  - vitamincereals_091101.csv
  - fruitvegamino_090406.csv
  - fruitvegmacro_091101.csv
  - fruitvegmin_090405.csv
  - fruitvegvitamin_0901101.csv
"""
import sys
import os
import pandas as pd
import re
from pathlib import Path
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session

# Add the backend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import SessionLocal, engine, Base
from app.models.models import FoodGroup, Food, NutrientType, Nutrient, FoodNutrient


class DataImporter:
    """Import nutrition data from CSV files with automatic type detection
    
    Supports flexible filenames and automatically detects:
    - Nutrient type (amino_acids, macronutrients, minerals, vitamins)
    - Food group (cereals, fruits, vegetables, or any custom name)
    """
    
    # Keywords to detect nutrient types from column headers
    AMINO_ACID_KEYWORDS = ['histidine', 'isoleucine', 'leucine', 'lysine', 'methionine', 
                           'phenylalanine', 'threonine', 'tryptophan', 'valine', 'arginine', 
                           'alanine', 'aspartic', 'cystine', 'glutamic', 'glycine', 'proline', 
                           'serine', 'tyrosine', 'amino', 'aa_', 'trp', 'thr', 'ile', 'leu',
                           'lys', 'met', 'cys', 'phe', 'tyr', 'val', 'arg', 'his']
    
    MACRONUTRIENT_KEYWORDS = ['energy', 'kcal', 'protein', 'carbohydrate', 'carbs', 'fat', 
                              'lipid', 'fiber', 'ash', 'water', 'moisture', 'kcal', 'cal', 'kj',
                              'energy_kc', 'procnt', 'a_protei', 'mfp_prot', 'chocdf', 'fasat',
                              'fams', 'fapu', 'chole', 'fib', 'sucs', 'phytac']
    
    MINERAL_KEYWORDS = ['calcium', 'ca', 'phosphorus', 'p_', 'magnesium', 'mg', 'potassium', 'k_', 
                        'iron', 'fe', 'zinc', 'zn', 'copper', 'cu', 'manganese', 'mn', 'sodium', 'na',
                        'iodine', 'i_', 'selenium', 'se', 'mineral', 'mfp_fe']
    
    VITAMIN_KEYWORDS = ['vitamin', 'retinol', 'a_', 'thiamine', 'b1', 'riboflavin', 'b2', 'niacin', 'b3',
                       'pantothenic', 'b5', 'pyridoxine', 'b6', 'cobalamin', 'b12', 'folate', 'folic',
                       'ascorbic', 'c_', 'calciferol', 'd_', 'tocopherol', 'e_', 'phylloquinone', 'k_',
                       'vita', 'vitd', 'vite', 'vitc', 'thia', 'ribf', 'nia', 'fol', 'pant', 'vit b6', 'vit b12']
    
    # Food group keywords
    FOOD_GROUP_KEYWORDS = {
        'cereals': ['bread', 'rice', 'wheat', 'corn', 'oat', 'grain', 'cereal', 'flour'],
        'fruits': ['apple', 'banana', 'orange', 'grape', 'fruit', 'berry', 'melon', 'citrus'],
        'vegetables': ['broccoli', 'carrot', 'spinach', 'lettuce', 'tomato', 'potato', 'pepper', 'vegetable'],
        'legumes': ['lentil', 'bean', 'pea', 'chickpea', 'legume'],
        'meat': ['beef', 'chicken', 'pork', 'lamb', 'meat', 'fish'],
        'dairy': ['milk', 'cheese', 'yogurt', 'dairy'],
    }
    GROUP_MARKER_PATTERN = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9_-]+$")
    KNOWN_UNIT_TOKENS = {
        "g",
        "mg",
        "mcg",
        "ug",
        "µg",
        "μg",
        "kcal",
        "cal",
        "kj",
        "iu",
        "ml",
        "l",
    }
    
    def __init__(self, excel_dir: str, db: Session):
        self.excel_dir = Path(excel_dir)
        self.db = db

    @staticmethod
    def normalize_cell(value) -> str:
        """Convert a CSV cell into a trimmed comparable string."""
        if pd.isna(value):
            return ""
        return str(value).strip()

    def is_group_marker(self, value) -> bool:
        """Group rows use alphabetic or mixed codes such as H, E, A1, F3, or GM2."""
        token = self.normalize_cell(value)
        return bool(token and self.GROUP_MARKER_PATTERN.match(token))

    def is_blank_row(self, row_values: List[str]) -> bool:
        return not any(value for value in row_values)

    def is_numeric_like(self, value) -> bool:
        token = self.normalize_cell(value)
        if not token:
            return False
        try:
            float(token.replace(",", ""))
            return True
        except ValueError:
            return False

    def looks_like_unit_token(self, token: str) -> bool:
        cleaned = self.normalize_cell(token).lower().replace(" ", "")
        if not cleaned:
            return False
        if cleaned in self.KNOWN_UNIT_TOKENS:
            return True
        return bool(re.fullmatch(r"(mg|mcg|ug|µg|μg|g|kcal|cal|kj|iu|ml|l)(m)?([a-z]{0,4})?(re)?(/[a-z0-9]+)?", cleaned))

    def parse_numeric_value(self, value):
        """Handle common CSV quirks such as decimal commas."""
        if pd.isna(value):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)

        token = str(value).strip()
        if not token:
            return 0.0

        if "," in token and "." not in token:
            if token.count(",") == 1:
                token = token.replace(",", ".")
            else:
                token = token.replace(",", "")
        else:
            token = token.replace(",", "")

        return float(token)

    def parse_header_definition(self, df: pd.DataFrame, row_idx: int):
        """
        Parse the active nutrient header row.

        We treat the first non-empty cell after column A as the nutrient type label
        (for example "Macronutrients"), and the remaining non-empty cells as the
        nutrient codes that should be read from later data rows.
        """
        row_values = [self.normalize_cell(df.iloc[row_idx, col_idx]) for col_idx in range(df.shape[1])]

        if self.is_group_marker(row_values[0]) or self.is_numeric_like(row_values[0]):
            return None

        non_empty = [(col_idx, value) for col_idx, value in enumerate(row_values[1:], start=1) if value]
        if len(non_empty) < 2:
            return None

        tokens = [value for _, value in non_empty]
        if all(self.looks_like_unit_token(token) for token in tokens):
            return None

        nutrient_type_label = tokens[0]
        nutrient_cols = []
        nutrient_units = {}

        for col_idx, nutrient_name in non_empty[1:]:
            nutrient_cols.append((col_idx, nutrient_name))

            unit = None
            if row_idx + 1 < df.shape[0]:
                unit_candidate = self.normalize_cell(df.iloc[row_idx + 1, col_idx])
                if unit_candidate and not self.is_group_marker(df.iloc[row_idx + 1, 0]) and not self.is_numeric_like(df.iloc[row_idx + 1, 0]):
                    unit = unit_candidate
            nutrient_units[nutrient_name] = unit or None

        if not nutrient_cols:
            return None

        return {
            "nutrient_type_label": nutrient_type_label,
            "nutrient_type_name": self.detect_nutrient_type([name for _, name in nutrient_cols]),
            "nutrient_cols": nutrient_cols,
            "nutrient_units": nutrient_units,
        }

    def extract_import_rows(self, df: pd.DataFrame) -> List[Dict[str, object]]:
        """
        Walk the file in order and build import rows tied to their explicit food group.

        Each food-group marker row starts a new logical section. Some sections repeat
        the nutrient headers, while others continue using the most recent header block.
        """
        records = []
        current_group = None
        current_header = None

        for row_idx in range(df.shape[0]):
            row_values = [self.normalize_cell(df.iloc[row_idx, col_idx]) for col_idx in range(df.shape[1])]

            if self.is_blank_row(row_values):
                continue

            if self.is_group_marker(row_values[0]):
                current_group = {
                    "code": row_values[0],
                    "name": row_values[1] or row_values[0],
                }
                continue

            if current_group is None:
                continue

            header = self.parse_header_definition(df, row_idx)
            if header:
                current_header = header
                continue

            if not self.is_numeric_like(row_values[0]):
                continue

            if not row_values[1] or current_header is None:
                continue

            records.append(
                {
                    "food_code": row_values[0],
                    "food_name": row_values[1],
                    "food_group_code": current_group["code"],
                    "food_group_name": current_group["name"],
                    "nutrient_type_name": current_header["nutrient_type_name"],
                    "nutrient_cols": current_header["nutrient_cols"],
                    "nutrient_units": current_header["nutrient_units"],
                    "row_idx": row_idx,
                }
            )

        return records
    
    def detect_nutrient_type(self, headers: List[str]) -> str:
        """Auto-detect nutrient type from column headers"""
        headers_lower = [h.lower() for h in headers]
        
        # Count keyword matches for each nutrient type
        amino_count = sum(1 for h in headers_lower for kw in self.AMINO_ACID_KEYWORDS if kw in h)
        macro_count = sum(1 for h in headers_lower for kw in self.MACRONUTRIENT_KEYWORDS if kw in h)
        mineral_count = sum(1 for h in headers_lower for kw in self.MINERAL_KEYWORDS if kw in h)
        vitamin_count = sum(1 for h in headers_lower for kw in self.VITAMIN_KEYWORDS if kw in h)
        
        scores = {
            'amino_acids': amino_count,
            'macronutrients': macro_count,
            'minerals': mineral_count,
            'vitamins': vitamin_count,
        }
        
        # Return the type with highest score
        detected_type = max(scores, key=scores.get)
        print(f"✓ Detected nutrient type: {detected_type} (scores: {scores})")
        return detected_type
    
    def detect_food_group(self, foods: List[str]) -> str:
        """Auto-detect food group from food names"""
        foods_lower = ' '.join([f.lower() for f in foods])
        
        group_scores = {}
        for group, keywords in self.FOOD_GROUP_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in foods_lower)
            group_scores[group] = score
        
        detected_group = max(group_scores, key=group_scores.get)
        
        # If no strong match, ask user or default
        if group_scores[detected_group] == 0:
            print(f"⚠️  Could not auto-detect food group. Using default 'Other'")
            detected_group = 'Other'
        else:
            print(f"✓ Detected food group: {detected_group}")
        
        return detected_group
    
    
    def get_or_create_food_group(self, name: str) -> int:
        """Get or create a food group and return its ID"""
        fg = self.db.query(FoodGroup).filter(FoodGroup.name == name).first()
        if not fg:
            fg = FoodGroup(name=name, description=f"{name} food group")
            self.db.add(fg)
            self.db.commit()
        return fg.id
    
    def get_or_create_nutrient_type(self, name: str, category: str = None) -> int:
        """Get or create a nutrient type and return its ID"""
        nt = self.db.query(NutrientType).filter(NutrientType.name == name).first()
        if not nt:
            nt = NutrientType(
                name=name,
                category=category or name,
                description=f"{name} nutrients"
            )
            self.db.add(nt)
            self.db.commit()
        return nt.id
    
    def get_or_create_nutrient(
        self,
        name: str,
        nutrient_type_id: int,
        unit: str = None,
        abbreviation: str = None,
    ) -> int:
        """Get or create a nutrient and return its ID"""
        nutrient = self.db.query(Nutrient).filter(
            Nutrient.name == name,
            Nutrient.nutrient_type_id == nutrient_type_id,
        ).first()
        
        if not nutrient:
            nutrient = Nutrient(
                name=name,
                nutrient_type_id=nutrient_type_id,
                unit=unit,
                abbreviation=abbreviation,
            )
            self.db.add(nutrient)
            self.db.commit()
        else:
            updated = False
            if unit and not nutrient.unit:
                nutrient.unit = unit
                updated = True
            if abbreviation and not nutrient.abbreviation:
                nutrient.abbreviation = abbreviation
                updated = True
            if updated:
                self.db.commit()
        return nutrient.id
    
    def get_or_create_food(self, name: str, food_group_id: int, code: str = None) -> int:
        """Get or create a food item and return its ID"""
        food = self.db.query(Food).filter(
            Food.name == name,
            Food.food_group_id == food_group_id,
        ).first()
        
        if not food:
            food = Food(
                name=name,
                food_group_id=food_group_id,
                code=code,
            )
            self.db.add(food)
            self.db.commit()
        return food.id
    
    def read_csv_file(self, file_path: Path) -> pd.DataFrame:
        """
        Read CSV file and return as DataFrame
        CSV format is REQUIRED for this importer (no Excel support)
        """
        try:
            df = pd.read_csv(str(file_path), header=None)
            print(f"\n📄 File: {file_path.name} (CSV)")
            print(f"   Shape: {df.shape[0]} rows × {df.shape[1]} columns")
            return df
        except Exception as e:
            print(f"❌ Error reading CSV file {file_path.name}: {str(e)[:80]}")
            return None
    
    def extract_food_and_nutrient_data(self, df: pd.DataFrame) -> Tuple[List[str], List[Tuple[int, str]], Dict[str, str]]:
        """
        Extract food names, nutrient columns with their indices, and units from DataFrame
        This is a flexible parser that handles various Excel layouts
        
        Layout is typically:
        Row 0: Title/Group name
        Row 1: Empty or category
        Row 2: Nutrient headers (Amino acids/Macronutrients/etc, then nutrient abbreviations)
        Row 3: Units (mg, g, etc.)
        Row 4: Empty or spacer
        Row 5+: Food data (ID, Name, then values)
        
        Returns:
            Tuple of (foods_list, [(col_idx, nutrient_name), ...], nutrient_units_dict)
        """
        foods = []
        nutrient_cols = []  # List of (column_index, nutrient_name) tuples
        nutrient_units = {}  # Maps nutrient name to its unit
        
        if df.shape[0] <= 4 or df.shape[1] <= 1:
            return foods, nutrient_cols, nutrient_units
        
        # Find nutrient headers - usually in row 2, starts from column 1
        # Row 2 typically has: NaN, "Amino acids" or nutrient category, then nutrient abbreviations
        
        # First, identify where nutrients are (row 2 or 3, columns 1 onwards)
        nutrient_row = None
        for row_idx in range(min(5, df.shape[0])):
            row_data = df.iloc[row_idx, 1:].tolist()
            # Count non-null values - nutrient rows have many non-null values
            non_null = sum(1 for x in row_data if pd.notna(x) and str(x).strip())
            if non_null > 3:  # Nutrient rows have many columns
                nutrient_row = row_idx
                break
        
        if nutrient_row is not None:
            # Extract nutrient names and track their ACTUAL column indices
            # This handles empty columns correctly
            for j in range(2, df.shape[1]):
                nutrient_name = df.iloc[nutrient_row, j]
                if pd.notna(nutrient_name):
                    nutrient_str = str(nutrient_name).strip()
                    if nutrient_str and len(nutrient_str) > 0 and nutrient_str.lower() not in ['nan', '']:
                        # Store the actual column index with the nutrient name
                        nutrient_cols.append((j, nutrient_str))
                        
                        # Extract unit from the next row (row 3 typically)
                        unit = ""
                        if nutrient_row + 1 < df.shape[0]:
                            unit_cell = df.iloc[nutrient_row + 1, j]
                            if pd.notna(unit_cell):
                                unit = str(unit_cell).strip()
                        nutrient_units[nutrient_str] = unit if unit else None
        
        if not nutrient_cols:
            return foods, nutrient_cols, nutrient_units
        
        # Find where food data starts - usually after row 4
        # Food data has: ID (numeric), Name (string), then numeric values
        data_start_row = max(4, nutrient_row + 2 if nutrient_row else 5)
        
        # Extract food names - they should be in column 1 (column 0 is usually an ID)
        for i in range(data_start_row, min(df.shape[0], 500)):
            food_id = df.iloc[i, 0]
            food_name = df.iloc[i, 1] if df.shape[1] > 1 else None
            
            # Skip rows where we don't have both ID and name
            if pd.isna(food_id) or pd.isna(food_name):
                continue
            
            food_name_str = str(food_name).strip()
            
            # Skip if food_name is empty or looks like a header
            if not food_name_str or food_name_str.lower() in ['name', 'food', 'id', 'code']:
                continue
            
            foods.append(food_name_str)
        
        return foods, nutrient_cols, nutrient_units
    
    def import_file(self, filename: str) -> bool:
        """Import a single CSV file with automatic nutrient type and food group detection
        
        Accepts any filename and auto-detects:
        - Nutrient type from column headers
        - Food groups from explicit section markers inside the CSV
        """
        # Validate that file has .csv extension
        if not filename.lower().endswith('.csv'):
            print(f"❌ ERROR: File must be CSV format! Provided: {filename}")
            return False
        
        file_path = self.excel_dir / filename
        
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            return False
        
        # Read CSV file
        df = self.read_csv_file(file_path)
        
        if df is None:
            return False
        
        import_rows = self.extract_import_rows(df)

        if not import_rows:
            print(f"⚠️  Could not extract data from {file_path.name}")
            return False

        unique_groups = sorted({row["food_group_name"] for row in import_rows})
        print(f"✓ Found {len(import_rows)} food rows across {len(unique_groups)} food groups: {', '.join(unique_groups)}")

        nutrient_type_ids = {}
        nutrient_ids = {}
        data_imported = 0

        for record in import_rows:
            try:
                food_group_id = self.get_or_create_food_group(record["food_group_name"])
                nutrient_type_name = record["nutrient_type_name"]
                if nutrient_type_name not in nutrient_type_ids:
                    nutrient_type_ids[nutrient_type_name] = self.get_or_create_nutrient_type(
                        nutrient_type_name,
                        category=nutrient_type_name.replace("_", " ").title(),
                    )
                nutrient_type_id = nutrient_type_ids[nutrient_type_name]

                food_id = self.get_or_create_food(
                    name=record["food_name"],
                    food_group_id=food_group_id,
                    code=record["food_code"],
                )

                for col_idx, nutrient_name in record["nutrient_cols"]:
                    nutrient_key = (nutrient_type_id, nutrient_name)
                    if nutrient_key not in nutrient_ids:
                        nutrient_ids[nutrient_key] = self.get_or_create_nutrient(
                            name=nutrient_name,
                            nutrient_type_id=nutrient_type_id,
                            unit=record["nutrient_units"].get(nutrient_name),
                            abbreviation=nutrient_name[:10] if len(nutrient_name) > 10 else nutrient_name,
                        )

                    nutrient_id = nutrient_ids[nutrient_key]
                    value = df.iloc[record["row_idx"], col_idx]
                    try:
                        value_float = self.parse_numeric_value(value)
                    except (ValueError, TypeError):
                        continue

                    existing = self.db.query(FoodNutrient).filter(
                        FoodNutrient.food_id == food_id,
                        FoodNutrient.nutrient_id == nutrient_id,
                    ).first()

                    if not existing:
                        fn = FoodNutrient(
                            food_id=food_id,
                            nutrient_id=nutrient_id,
                            nutrient_type_id=nutrient_type_id,
                            value=value_float,
                            per_unit=record["nutrient_units"].get(nutrient_name),
                            data_source=filename,
                        )
                        self.db.add(fn)
                        data_imported += 1

                if data_imported % 50 == 0:
                    self.db.commit()
                    print(f"  ✓ Processed {data_imported} nutrient values...")

            except Exception as e:
                print(f"  Error processing food {record['food_name']} in group {record['food_group_name']}: {e}")
                self.db.rollback()
        
        # Final commit
        self.db.commit()
        print(f"✅ Successfully imported {data_imported} nutrient values from {filename}")
        return True
    
    def import_all(self):
        """Import all Excel files"""
        print("\n" + "=" * 60)
        print("NUTRITION DATA IMPORT TOOL")
        print("=" * 60)
        
        success_count = 0
        for filename in sorted(self.file_mappings.keys()):
            if self.import_file(filename):
                success_count += 1
        
        print("\n" + "=" * 60)
        print(f"✅ Import complete! Successfully imported {success_count} files")
        print("=" * 60 + "\n")


def main():
    """Main import function"""
    # Create database session
    db = SessionLocal()
    
    try:
        # Initialize importer
        excel_dir = Path(__file__).parent.parent  # NUTRITION-ANALYTIC-APP directory
        importer = DataImporter(str(excel_dir), db)
        
        # Import all files
        importer.import_all()
        
        # Print summary
        print("\n📊 DATABASE SUMMARY:")
        print(f"Food Groups: {db.query(FoodGroup).count()}")
        print(f"Foods: {db.query(Food).count()}")
        print(f"Nutrient Types: {db.query(NutrientType).count()}")
        print(f"Nutrients: {db.query(Nutrient).count()}")
        print(f"Food-Nutrient Values: {db.query(FoodNutrient).count()}\n")
        
    except Exception as e:
        print(f"❌ Error during import: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
