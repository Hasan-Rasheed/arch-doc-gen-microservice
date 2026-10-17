import pytest

from app.acadnusx import fold, is_legacy_georgian_font, to_georgian
from app.layers import classify, normalize


@pytest.mark.parametrize("latin, georgian", [
    ("sacxovrebeli farTobi", "საცხოვრებელი ფართობი"),
    ("kibe,derefani, lifti", "კიბე,დერეფანი, ლიფტი"),
    ("Wrilis aRniSvna", "ჭრილის აღნიშვნა"),
    ("nikoloz CxaiZe", "ნიკოლოზ ჩხაიძე"),
    ("bina-01 65.3 kv.", "ბინა-01 65.3 კვ."),
])
def test_to_georgian(latin, georgian):
    assert to_georgian(latin) == georgian


def test_fold_matches_all_spellings():
    assert fold("კედელი") == fold("kedeli") == fold("KEDELI")
    assert fold("SAXANDZRO") == fold("saxanZro") == fold("სახანძრო")


def test_legacy_font_detection():
    assert is_legacy_georgian_font("AcadMtavr")
    assert is_legacy_georgian_font("ABCDEF+AcadNusx")
    assert is_legacy_georgian_font("AvazaMtavruli") and is_legacy_georgian_font("AvazaMtavruli,Bold")
    assert is_legacy_georgian_font("Avaza") and is_legacy_georgian_font("AvantGardeMtavruli")
    assert not is_legacy_georgian_font("BPGExtraSquareMtavruli")  # Unicode, has real "EXIT"
    assert not is_legacy_georgian_font("Sylfaen")
    assert not is_legacy_georgian_font("ArialMT")


def test_normalize_archicad_new_prefix():
    assert normalize("New_2D Drafting - General_Pen_No__12") == "2d drafting - general"


def test_normalize():
    assert normalize("WALL-INT   (NEO-A)") == "wall-int"
    assert normalize("Axis-Art") == "axis"
    assert normalize("5.H-Vijat ne dukje_Pen_No__7") == "5.h-vijat ne dukje"
    assert normalize("-------DAKAVEBULOBIS GEGMA") == "dakavebulobis gegma"


# Every layer seen in gegmebi (2).pdf, with the category its rendered content proved.
GEGMEBI = {
    "COLUMN    (NEO-A)": "COLUMN",
    "COLUMN-H   (NEO-A)": "WALL_FILL",
    "WALL-INT   (NEO-A)": "WALL",
    "WALL-EXT   (NEO-A)": "WALL",
    "WALL-H   (NEO-A)": "WALL_FILL",
    "FINISH-WALL-EXT   (NEO-A)": "FINISH_EXT",
    "dablokili": "WALL",
    "kedeli": "SITE",
    "DOOR    (NEO-A)": "DOOR",
    "A-Door": "DOOR",
    "WIND   (NEO-A)": "WINDOW",
    "WIND-FRAME   (NEO-A)": "WINDOW",
    "FLOOR-HANDRAIL-EXT   (NEO-A)": "RAILING",
    "FLOOR-STR-INT   (NEO-A)": "VERTICAL",
    "FLOOR-STR-EXT-SYMBOL   (NEO-A)": "VERTICAL",
    "FLOOR-TXT   (NEO-A)": "ROOM_TEXT",
    "FLOOR-H   (NEO-A)": "FLOOR_PATTERN",
    "FURNITURE   (NEO-A)": "FURNITURE",
    "FURNIT-KITCHEN   (NEO-A)": "FURNITURE",
    "FURNIT-LIGHT   (NEO-A)": "FURNITURE",
    "FURNIT-SANITARY   (NEO-A)": "SANITARY",
    "duravit": "SANITARY",
    "სვლაგეზები": "SANITARY",
    "RISER-MEP   (NEO-A)": "MEP",
    "BEAM   (NEO-A)": "OVERHEAD_HIDDEN",
    "5.H-Vijat ne dukje": "OVERHEAD_HIDDEN",
    "GRID   (NEO-A)": "GRID",
    "DIM-01    (NEO-A)": "DIMENSION",
    "DIM-TXT-01    (NEO-A)": "DIMENSION",
    "DIM-DETAIL-01    (NEO-A)": "DIMENSION",
    "SECTION-SYMBOL-01   (NEO-A)": "ANNOTATION",
    "SYMBOL-LAYOUT   (NEO-A)": "ANNOTATION",
    "SIGN   (NEO-A)": "ANNOTATION",
    "DETAIL-05    (NEO-A)": "ANNOTATION",
    "ROOF- EQUIP-TXT   (NEO-A)": "ANNOTATION",
    "HEIGHT": "ANNOTATION",
    "karis cecxlmedegoba": "ANNOTATION",
    "LI_Fire Rating": "DERIVATIVE_FIRE",
    "-------EXIT": "DERIVATIVE_FIRE",
    "Z01_Nakveti": "SITE",
    "Hatch-art": "SITE",
    "TOPO": "SITE",
    "C-TOPO-MAJR": "SITE",
    "ferdobi": "SITE",
    "shenoba": "SITE",
    "kanalizacia": "MEP",
    "kibe": "SITE",
    "pirobiti": "SHEET",
    "GEN-TITLE   (NEO-A)": "SHEET",
    "Defpoint": "SHEET",
    "0": "UNKNOWN",
}

# Layers the architects added for the derivative sheets in DownloadServlet (1).pdf.
TARGET = {
    "-------DAKAVEBULOBIS GEGMA": "DERIVATIVE_OCCUPANCY",
    "AN_DAKAVEBULOBA": "DERIVATIVE_OCCUPANCY",
    "--------SAXANDZRO_GEGMA": "DERIVATIVE_FIRE",
    "სახანძრო": "DERIVATIVE_FIRE",
    "DFRANG_41_FIRERESISTANCE": "DERIVATIVE_FIRE",
    "AN_Emergency Exit": "DERIVATIVE_FIRE",
    "-------MISACVDOMOBIS_GEGMA": "DERIVATIVE_ACCESS",
    "A-COLUMN": "COLUMN",
    "Axis-Art": "GRID",
    "Dimension-Art": "DIMENSION",
}

# Standard / other-language names (not yet seen in our files).
STANDARD = {
    "A-WALL": "WALL",
    "A-WALL-FULL": "WALL",
    "A-WALL-PRHT": "WALL",
    "A-WALL-PATT": "WALL_FILL",
    "A-DOOR": "DOOR",
    "A-DOOR-IDEN": "ANNOTATION",
    "A-GLAZ": "WINDOW",
    "A-GLAZ-IDEN": "ANNOTATION",
    "S-COLS": "COLUMN",
    "A-FURN": "FURNITURE",
    "A-FLOR-PATT": "FLOOR_PATTERN",
    "A-AREA-IDEN": "ROOM_TEXT",
    "A-GRID": "GRID",
    "A-ANNO-DIMS": "DIMENSION",
    "კედელი": "WALL",
    "ტიხარი": "WALL",
    "კარები": "DOOR",
    "ფანჯრები": "WINDOW",
    "STENA": "WALL",
    "Стена": "WALL",
    "OKNA": "WINDOW",
}


# Seen in the other sample sets (Master / Grand Master / new/, several offices, mostly ARCHICAD).
SAMPLES = {
    "Structural - Bearing": "WALL",
    "Structural - Combined": "WALL",
    "Structural - Grid": "GRID",
    "Structural - Stair & Railing": "VERTICAL",
    "C Exterior walls": "WALL",
    "Interior - Partition": "WALL",
    "Finish - Wall": "FINISH_EXT",
    "!კედლის საათები - 2 საათი - ლაინებში": "DERIVATIVE_FIRE",  # must never be a wall
    "41": "DERIVATIVE_FIRE",
    "000-41": "DERIVATIVE_FIRE",
    "001 dakavebuloba": "DERIVATIVE_OCCUPANCY",
    "დაკავებულობები გეგმა": "DERIVATIVE_OCCUPANCY",
    "New_-------MISACVDOMOBIS_GEGMA_Pen_No__7": "DERIVATIVE_ACCESS",
    "Интерьер - Мебель": "FURNITURE",
    "#Zone.working": "ROOM_TEXT",
    "CONT-MJR": "SITE",
}


@pytest.mark.parametrize("name, expected", {**GEGMEBI, **TARGET, **STANDARD, **SAMPLES}.items())
def test_classify(name, expected):
    assert classify(name).category == expected, classify(name)
