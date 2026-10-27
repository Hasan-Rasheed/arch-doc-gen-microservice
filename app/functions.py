"""Room functions → occupancy groups, for buildings whose rooms aren't grouped into apartments or
offices (clinics, schools, universities). Groups follow rulebook №41 chapter 3 (IBC 302):

  თვ assembly · სქ business · სგ educational · სმ factory · დწ institutional · სვ mercantile ·
  სც residential · სწ storage · დს utility/accessory

Words are matched at the start of a room's name tokens in any spelling (Georgian, AcadNusx
Latin, plain Latin — acadnusx.starts_with), so they're word stems.
"""

from .acadnusx import folded, starts_with

# Strong function words: the room is that function wherever it is, and an apartment- or
# storage-style unit must not grow into it.
STRONG = {
    "institutional": folded((
        "პალატა", "საოპერაციო", "საპროცედურო", "რეანიმაც", "ინტენსიურ", "ექთნის", "სტერილიზ",
        "მშობიარ", "იზოლატორ", "ward", "operating",
    )),
    "business": folded((
        "ლაბორატორ", "აუდიტორ", "დეკანატ", "საორდინატორო", "ადმინისტრაც", "რეგისტრატურ",
        "სარეგისტრაციო", "სტომატ", "დიაგნოსტ", "გასინჯვ", "ექიმის", "ექიმი", "მისაღები",
        "სათათბირო", "მოსაცდელ", "meeting", "waiting",
        "lab", "laboratory", "lecture", "clinic", "reception",
        # University teaching counts as business under IBC 304 (education above 12th grade).
    )),
    "assembly": folded(("საკონფერენციო", "სააქტო", "სპორტული", "conference")),
    "mercantile": folded(("აფთიაქ", "pharmacy")),
    "educational": folded(("საკლასო", "classroom", "საბავშვო")),
    "storage": folded(("არქივ", "archive")),
    "factory": folded(("სახელოსნო", "workshop")),
}

# Words that name a function in a public building but something else inside a dwelling
# ("კაბინეტი" = doctor's office in a clinic, a study in an apartment). Applied only to rooms no
# unit claimed.
AMBIGUOUS = {
    "business": folded(("კაბინეტ", "მენეჯერ", "office", "cabinet")),
    "assembly": folded(("სასადილო",)),
}

# Support rooms: no group of their own; they take the group of the rooms around them.
ACCESSORY = folded((
    "დამხმარე", "სანიტარ", "საპირფარეშო", "გასახდელ", "შლუზ", "ნარჩენ", "ტექნიკ", "ელექტრო",
    "სატუმბ", "სერვერ", "საშხაპე", "სამრეცხაო", "სამზარეულო", "მედიკამენტ", "დასასვენებ",
    "აპარატურ", "wc", "toilet",
))


# Occupancy groups. "transient" is სც-1 (hotels, hostels); "residential" is სც-2 (apartments).
GROUPS = {"residential", "transient", "business", "mercantile", "assembly", "institutional", "educational",
          "factory", "storage", "parking"}
# Dwellings: fire partitions between them (§420.2) and the accessibility rules apply to both.
DWELLING = {"residential", "transient"}

# What an external classifier (the backend's LLM step) may say about a room name: its group (a
# function room), "unit:<group>" (the room is a separately occupied unit — an apartment, hotel
# room, office suite, shop — so a zone starts there in any building, whatever it's called),
# "accessory" (a support room) or "circulation".
EXTRA_CLASSES = GROUPS | {f"unit:{g}" for g in GROUPS} | {"accessory", "circulation"}


def unit_role(cls: str | None) -> str | None:
    """The group of a "unit:<group>" classification, else None."""
    return cls[5:] if cls and cls.startswith("unit:") else None


def room_name(words: list[str]) -> str:
    """A room's name as a phrase: its name words in order ("ექიმების დასასვენებელი სივრცე")."""
    from .acadnusx import is_name_word
    return " ".join(w.rstrip(",.") for w in words if is_name_word(w))[:60]


def extra_class(words: list[str], extra: dict[str, str] | None) -> str | None:
    """Class from an externally supplied {room name: class} map, matched on the folded name."""
    if not extra:
        return None
    from .acadnusx import fold
    return extra.get(fold(room_name(words)))


def function_class(words: list[str], strong_only: bool = False) -> str | None:
    tables = [STRONG] if strong_only else [STRONG, AMBIGUOUS]
    for table in tables:
        for cls, stems in table.items():
            if any(starts_with(w, stems) for w in words):
                return cls
    return None


def is_accessory(words: list[str]) -> bool:
    return any(starts_with(w, ACCESSORY) for w in words)
