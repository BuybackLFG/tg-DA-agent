import json
from pathlib import Path
from typing import Any

import pandas as pd


def load_dataset(path: Path) -> pd.DataFrame:
    """Load a CSV or Excel file into a pandas DataFrame."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    elif suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}")


def _serialize_value(value: Any) -> Any:
    """Convert non-JSON-serializable values (e.g. NaN, int64) to native Python types."""
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def profile_dataset(df: pd.DataFrame) -> dict[str, Any]:
    """Return a lightweight profile of the DataFrame suitable for LLM consumption."""
    rows, cols = df.shape
    dtypes = {col: str(df[col].dtype) for col in df.columns}

    # Missing values
    missing = {col: int(df[col].isna().sum()) for col in df.columns}
    missing_pct = {
        col: round(100 * missing[col] / rows, 2) if rows else 0.0
        for col in df.columns
    }

    # Numeric columns summary
    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    numeric_summary = {}
    for col in numeric_cols:
        desc = df[col].describe()
        numeric_summary[col] = {
            "mean": _serialize_value(desc.get("mean")),
            "std": _serialize_value(desc.get("std")),
            "min": _serialize_value(desc.get("min")),
            "25%": _serialize_value(desc.get("25%")),
            "50%": _serialize_value(desc.get("50%")),
            "75%": _serialize_value(desc.get("75%")),
            "max": _serialize_value(desc.get("max")),
        }

    # Categorical / object columns — top unique values
    cat_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    cat_summary = {}
    for col in cat_cols:
        top = df[col].value_counts().head(5)
        cat_summary[col] = {
            "unique_count": int(df[col].nunique()),
            "top_values": {str(k): int(v) for k, v in top.items()},
        }

    # DateTime columns
    datetime_cols = df.select_dtypes(include=["datetime"]).columns.tolist()
    datetime_summary = {}
    for col in datetime_cols:
        datetime_summary[col] = {
            "min": _serialize_value(df[col].min()),
            "max": _serialize_value(df[col].max()),
            "unique_count": int(df[col].nunique()),
        }

    profile = {
        "shape": {"rows": rows, "columns": cols},
        "columns": list(df.columns),
        "dtypes": dtypes,
        "missing": {"counts": missing, "percentages": missing_pct},
        "numeric_summary": numeric_summary,
        "categorical_summary": cat_summary,
        "datetime_summary": datetime_summary,
        "sample_rows": df.head(5).fillna("").astype(str).to_dict(orient="records"),
    }
    return profile


def profile_to_text(profile: dict) -> str:
    """Convert the JSON profile into a concise human-readable string."""
    lines = [
        f"📊 Датасет: {profile['shape']['rows']} строк, {profile['shape']['columns']} колонок",
        "",
        "Колонки и типы:",
    ]
    for col, dtype in profile["dtypes"].items():
        missing = profile["missing"]["percentages"].get(col, 0)
        lines.append(f"  • {col} ({dtype}) — пропусков: {missing}%")

    if profile["numeric_summary"]:
        lines.append("\nЧисловые колонки (основные метрики):")
        for col, stats in profile["numeric_summary"].items():
            lines.append(
                f"  • {col}: mean={stats['mean']:.2f}, min={stats['min']}, max={stats['max']}"
            )

    if profile["categorical_summary"]:
        lines.append("\nКатегориальные колонки:")
        for col, stats in profile["categorical_summary"].items():
            top = ", ".join(stats["top_values"].keys())
            lines.append(f"  • {col}: {stats['unique_count']} уникальных, топ: {top}")

    if profile["datetime_summary"]:
        lines.append("\nДата/время колонки:")
        for col, stats in profile["datetime_summary"].items():
            lines.append(f"  • {col}: {stats['min']} → {stats['max']}")

    return "\n".join(lines)
