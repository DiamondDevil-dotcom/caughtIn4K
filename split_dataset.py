import os
import pandas as pd
from sklearn.model_selection import train_test_split

# ========= CONFIG =========
SOURCE_DATASET = r"C:\Users\ASUS\Desktop\SDC 2 Project\Ghost_FL_Flower\data\CICIOT23"
OUTPUT_DATASET = r"C:\Users\ASUS\Desktop\SDC 2 Project\Dataset"

RANDOM_STATE = 42
TEST_SIZE = 0.5
# ==========================


def split_csv(input_file, output_folder, filename):
    print(f"\nProcessing {filename}...")

    df = pd.read_csv(input_file)

    # Shuffle before splitting
    df = df.sample(frac=1, random_state=RANDOM_STATE).reset_index(drop=True)

    client0, client1 = train_test_split(
        df,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        shuffle=True,
    )

    os.makedirs(os.path.join(output_folder, "client0"), exist_ok=True)
    os.makedirs(os.path.join(output_folder, "client1"), exist_ok=True)

    client0.to_csv(
        os.path.join(output_folder, "client0", filename),
        index=False,
    )

    client1.to_csv(
        os.path.join(output_folder, "client1", filename),
        index=False,
    )

    print(f"{filename} split completed.")
    print(f"Client0: {len(client0)} rows")
    print(f"Client1: {len(client1)} rows")


split_csv(
    os.path.join(SOURCE_DATASET, "train", "train.csv"),
    OUTPUT_DATASET,
    "train.csv",
)

split_csv(
    os.path.join(SOURCE_DATASET, "validation", "validation.csv"),
    OUTPUT_DATASET,
    "validation.csv",
)

split_csv(
    os.path.join(SOURCE_DATASET, "test", "test.csv"),
    OUTPUT_DATASET,
    "test.csv",
)

print("\nDone!")