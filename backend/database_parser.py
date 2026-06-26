"""
Database Parser Module - Parse SQLite database files and CSV files
"""

import os
import json
import csv
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import datetime


class DatabaseInfo:
    """Database information"""

    def __init__(
        self,
        db_name: str,
        tables: List[Dict[str, Any]] = None,
        file_path: str = None,
        uploaded_at: str = None
    ):
        self.db_name = db_name
        self.tables = tables or []
        self.file_path = file_path
        self.uploaded_at = uploaded_at or datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "db_name": self.db_name,
            "tables": self.tables,
            "file_path": self.file_path,
            "uploaded_at": self.uploaded_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseInfo":
        return cls(
            db_name=data["db_name"],
            tables=data.get("tables", []),
            file_path=data.get("file_path"),
            uploaded_at=data.get("uploaded_at")
        )


class TableInfo:
    """Table information"""

    def __init__(
        self,
        table_name: str,
        columns: List[Dict[str, Any]] = None,
        row_count: int = 0
    ):
        self.table_name = table_name
        self.columns = columns or []
        self.row_count = row_count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "columns": self.columns,
            "row_count": self.row_count
        }


class ColumnInfo:
    """Column information"""

    def __init__(
        self,
        column_name: str,
        data_type: str,
        is_nullable: bool = True,
        is_primary_key: bool = False,
        value_range: Dict[str, Any] = None
    ):
        self.column_name = column_name
        self.data_type = data_type
        self.is_nullable = is_nullable
        self.is_primary_key = is_primary_key
        self.value_range = value_range or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "column_name": self.column_name,
            "data_type": self.data_type,
            "is_nullable": self.is_nullable,
            "is_primary_key": self.is_primary_key,
            "value_range": self.value_range
        }


def get_value_range_for_column(conn: sqlite3.Connection, table_name: str, column_name: str, data_type: str) -> Dict[str, Any]:
    """
    获取字段的值域

    Args:
        conn: 数据库连接
        table_name: 表名
        column_name: 字段名
        data_type: 数据类型

    Returns:
        值域字典
    """
    try:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]

        if row_count == 0:
            return {"type": "empty"}

        # Get value range based on data type
        if data_type.upper() in ("INTEGER", "REAL", "NUMERIC", "INT", "FLOAT", "DOUBLE"):
            # 数值类型：获取min和max
            cursor = conn.execute(f"""
                SELECT MIN({column_name}), MAX({column_name})
                FROM {table_name}
                WHERE {column_name} IS NOT NULL
            """)
            result = cursor.fetchone()
            if result and result[0] is not None and result[1] is not None:
                return {
                    "type": "numeric",
                    "min": result[0],
                    "max": result[1]
                }
            return {"type": "numeric", "min": None, "max": None}

        elif data_type.upper() in ("TEXT", "VARCHAR", "CHAR", "BLOB"):
            # String type: get all distinct values
            cursor = conn.execute(f"""
                SELECT DISTINCT {column_name}
                FROM {table_name}
                WHERE {column_name} IS NOT NULL
                LIMIT 100
            """)
            values = [row[0] for row in cursor.fetchall() if row[0] is not None]
            return {
                "type": "text",
                "unique_count": len(set(values)),
                "sample_values": values[:20]  # Return up to 20 sample values
            }

        elif data_type.upper() == "BLOB":
            return {"type": "binary", "description": "Binary data"}

        return {"type": "unknown"}

    except Exception as e:
        return {"type": "error", "message": str(e)}


def parse_sqlite_database(file_path: str, db_name_override: Optional[str] = None) -> DatabaseInfo:
    """
    Parse SQLite database file

    Args:
        file_path: Database file path
        db_name_override: Custom database name (optional)

    Returns:
        DatabaseInfo: Database information object
    """
    db_name = db_name_override if db_name_override else os.path.splitext(os.path.basename(file_path))[0]

    try:
        conn = sqlite3.connect(file_path)
        cursor = conn.cursor()

        # 获取所有表
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """)
        tables = cursor.fetchall()

        table_info_list = []

        for (table_name,) in tables:
            # Get table info
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns_info = cursor.fetchall()

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            row_count = cursor.fetchone()[0]

            columns = []

            for col in columns_info:
                # col: (cid, name, type, notnull, dflt_value, pk)
                column_name = col[1]
                data_type = col[2] or "UNKNOWN"
                is_nullable = not bool(col[3])
                is_primary_key = bool(col[5])

                # Get value range
                value_range = get_value_range_for_column(conn, table_name, column_name, data_type)

                column_info = ColumnInfo(
                    column_name=column_name,
                    data_type=data_type,
                    is_nullable=is_nullable,
                    is_primary_key=is_primary_key,
                    value_range=value_range
                )
                columns.append(column_info.to_dict())

            table_info = TableInfo(
                table_name=table_name,
                columns=columns,
                row_count=row_count
            )
            table_info_list.append(table_info.to_dict())

        conn.close()

        return DatabaseInfo(
            db_name=db_name,
            tables=table_info_list,
            file_path=file_path
        )

    except Exception as e:
        raise Exception(f"Failed to parse database: {str(e)}")


def parse_csv_file(file_path: str, db_name_override: Optional[str] = None) -> DatabaseInfo:
    """
    Parse CSV file

    Args:
        file_path: CSV file path
        db_name_override: Custom database name (optional)

    Returns:
        DatabaseInfo: Database information object
    """
    db_name = db_name_override if db_name_override else os.path.splitext(os.path.basename(file_path))[0]

    try:
        # Auto-detect encoding and read file (handle BOM, GBK, etc.)
        raw_data = open(file_path, "rb").read()

        # Skip UTF-8 BOM
        if raw_data.startswith(b'\xef\xbb\xbf'):
            raw_data = raw_data[3:]
            encoding = 'utf-8'
        # Detect UTF-8
        elif _is_valid_utf8(raw_data):
            encoding = 'utf-8'
        else:
            # Try GBK
            encoding = 'gbk'

        try:
            text = raw_data.decode(encoding)
        except UnicodeDecodeError:
            text = raw_data.decode('utf-8', errors='replace')

        # Parse using csv module
        from io import StringIO
        reader = csv.reader(StringIO(text))
        rows = list(reader)

        if len(rows) == 0:
            return DatabaseInfo(
                db_name=db_name,
                tables=[],
                file_path=file_path
            )

        # First row as header (column names)
        headers = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []

        # Analyze data type and value range for each column
        # Auto-detect and skip: 1) columns with empty names  2) columns that look like index columns
        columns = []
        for i, header in enumerate(headers):
            header_str = (header or "").strip()
            # Skip columns with empty names
            if not header_str:
                continue
            # Skip obvious index columns: header is "id"/"index"/"idx"/"Unnamed: 0" etc.
            lower_header = header_str.lower()
            if lower_header in ("id", "index", "idx", "no", "no.", "number", "row", "序号", "索引"):
                continue
            if lower_header.startswith("unnamed:"):
                continue

            col_values = [row[i] for row in data_rows if i < len(row) and row[i] not in (None, "")]
            col_info = analyze_csv_column(header_str, col_values)
            columns.append(col_info)

        # Build table info (CSV as single table)
        table_info = TableInfo(
            table_name="data",
            columns=columns,
            row_count=len(data_rows)
        )

        return DatabaseInfo(
            db_name=db_name,
            tables=[table_info.to_dict()],
            file_path=file_path
        )

    except Exception as e:
        raise Exception(f"Failed to parse CSV file: {str(e)}")


def _is_valid_utf8(data: bytes) -> bool:
    """Detect if data is valid UTF-8 encoding"""
    try:
        data.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def analyze_csv_column(column_name: str, values: List[str]) -> Dict[str, Any]:
    """
    Analyze CSV column data type and value range

    Args:
        column_name: Column name
        values: List of column values

    Returns:
        Column information dictionary
    """
    if len(values) == 0:
        return ColumnInfo(
            column_name=column_name,
            data_type="TEXT",
            is_nullable=True,
            is_primary_key=False,
            value_range={"type": "empty"}
        ).to_dict()

    # Detect data type
    numeric_values = []
    for v in values:
        try:
            numeric_values.append(float(v))
        except (ValueError, TypeError):
            numeric_values.append(None)

    # 如果超过50%的值可以转为数字，则认为是数值类型
    valid_numeric = [v for v in numeric_values if v is not None]
    if len(valid_numeric) / len(values) > 0.5:
        min_val = min(valid_numeric)
        max_val = max(valid_numeric)
        return ColumnInfo(
            column_name=column_name,
            data_type="NUMERIC",
            is_nullable=True,
            is_primary_key=False,
            value_range={
                "type": "numeric",
                "min": min_val,
                "max": max_val
            }
        ).to_dict()
    else:
        # String type
        unique_values = list(set(values))
        return ColumnInfo(
            column_name=column_name,
            data_type="TEXT",
            is_nullable=True,
            is_primary_key=False,
            value_range={
                "type": "text",
                "unique_count": len(unique_values),
                "sample_values": unique_values[:20]
            }
        ).to_dict()


def parse_uploaded_database(file_data: bytes, filename: str, project_id: str, project_store) -> DatabaseInfo:
    """
    Parse uploaded database file and save to project
    Automatically select parsing method based on file extension:
    - .db, .sqlite, .sqlite3 -> SQLite parsing
    - .csv -> CSV parsing

    Args:
        file_data: File data
        filename: File name
        project_id: Project ID
        project_store: Project store instance

    Returns:
        DatabaseInfo: Database information object
    """
    import tempfile

    file_ext = os.path.splitext(filename)[1].lower()
    is_csv = file_ext == ".csv"

    # Select temp file suffix based on file type
    tmp_suffix = ".csv" if is_csv else ".db"

    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=tmp_suffix) as tmp_file:
        tmp_file.write(file_data)
        tmp_path = tmp_file.name

    try:
        # Select parsing method based on file type
        if is_csv:
            # CSV uses original filename as db_name (without extension)
            db_info = parse_csv_file(tmp_path, db_name_override=os.path.splitext(filename)[0])
        else:
            db_info = parse_sqlite_database(tmp_path)

        # Save file copy to project directory
        project_db_dir = project_store.get_project_path(project_id, "databases")
        if not os.path.exists(project_db_dir):
            os.makedirs(project_db_dir, exist_ok=True)

        dest_path = os.path.join(project_db_dir, filename)
        with open(tmp_path, "rb") as src:
            with open(dest_path, "wb") as dst:
                dst.write(file_data)

        db_info.file_path = dest_path

        # Update project's database.json
        db_file_path = project_store.get_project_path(project_id, "database.json")
        if os.path.exists(db_file_path):
            with open(db_file_path, "r", encoding="utf-8") as f:
                db_data = json.load(f)
        else:
            db_data = {"databases": []}

        # Check if database with same name already exists
        existing_idx = None
        for i, db in enumerate(db_data["databases"]):
            if db["db_name"] == db_info.db_name:
                existing_idx = i
                break

        if existing_idx is not None:
            db_data["databases"][existing_idx] = db_info.to_dict()
        else:
            db_data["databases"].append(db_info.to_dict())

        project_store.save_project_file(project_id, "database.json", db_data)

        return db_info

    finally:
        # Delete temporary file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def get_project_databases(project_store, project_id: str) -> List[DatabaseInfo]:
    """
    Get all databases for a project

    Args:
        project_store: Project store instance
        project_id: Project ID

    Returns:
        List[DatabaseInfo]: List of database information objects
    """
    db_file_path = project_store.get_project_path(project_id, "database.json")
    if not os.path.exists(db_file_path):
        return []

    with open(db_file_path, "r", encoding="utf-8") as f:
        db_data = json.load(f)

    return [DatabaseInfo.from_dict(db) for db in db_data.get("databases", [])]
