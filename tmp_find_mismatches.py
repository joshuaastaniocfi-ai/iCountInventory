import os, sqlite3
os.environ['DATABASE_URL'] = 'sqlite:///instance/inventory.db'

# Parse the user's list
raw = """Coke Zero  (1case=24cans)\tCounter
Coke regular (1case=24cans)\tCounter
Nature spring (1case=24cans)\tCounter
Royal reg. 330ml (1case=24cans)\tCounter
Sprite regular (1case=24btls)\tCounter
coke light 330ml (1case=24cans)\tCounter
mango concentrate (1bt=2000ml)\tSoda
sarsi (1case=24cans)\tCounter
Boneless Barbq (1order=150grams)\tMaincourse
Buffalo wings 6pcs (1order=6pcs)\tMaincourse
Buffalo wings 8pcs (1order=8pcs)\tMaincourse
CHIX CORDON BLEU (1order=250grams)\tMaincourse
Fried Chicken 2pcs (1order=2pcs)\tSandwich
Fried Chicken 4pcs (1order=4pcs)\tSandwich
ADOBO SAUCE (1gal=3785grams)\tMaincourse
Chicken breading (1gal=3785grams)\tSandwich
Chicken powder (1case=12pack @ 1000grams)\tMaincourse
Cooking Oil (1jug=17000ml)\tMaincourse
Del monte Catsup (1btl=340grams)\tMaincourse
Java sauce (1gal=3785grams)\tMaincourse
knorr liquid seasoning/ 130ml\tMaincourse
Mang tomas  (1btl=325g)\tMaincourse
Marinara sauce (1gal=3785grams)\tSandwich
Mexican sauce (1kl=1000grams)\tSandwich
Mushroom gravy (1case=6packs@500grams)\tSandwich
Oregano leaves (1pack=1000grams)\tSandwich
PARMESAN CHEESE (1btl=227grams)\tSandwich
Palabok Sauce (1pack=1000grams)\tSandwich
Ranch Dressing (1pack=120grams)\tSandwich
Spaghetti sauce (1pack=1000grams)\tSandwich
Suka Datu puti (1gal=3785grams)\tMaincourse
Taco dressing (1gal=3785grams)\tSandwich
knorr liquid seasoning (1gal=3785grams)\tMaincourse
1pack=2500grmas\tSoda
CHOCO SYRUP (1gal=3785grams)\tSoda
Cherry w/ stem (1btl=1kgrams/76pcs)\tSoda
Cocoa Powder (1pack=250grmas)\tCoffee Bar
Coffee beans Arabica (1pack=1000grams)\tCoffee Bar
Collagen (1pc)\tCoffee Bar
Condensed (1can=300ml)\tSoda
Cream Corn (1can=425grams)\tSoda
Evap Milk (1can=370ml)\tSoda
GULAMAN RED powder (1pack=1000grams)\tSoda
Hazelnut syrup torani (1btl=750ml)\tCoffee Bar
Kernel Corn (1can=425grams)\tSoda
LANGKA (1case=12jars@907grams)\tSoda
Langka Candy (1pack=250grmas)\tSoda
Macapuno balls (1btl=122pcs)\tSoda
Milk Full Cream Hanna (1box=1000grams)\tCoffee Bar
Nachos violet (1pack=25pcs@200grams)\tSandwich
Nestle cream (1box=340grams)\tSandwich
Strawberry Syrup (1gal=3785grams)\tSoda
Whipping Cream (1pack=1000grams)\tSoda
nata white (1bottle=340grams)\tSoda
peach halves (1can=820grams@30slices)\tSoda
Aoili dressing (1gal=3785grams)\tSandwich
Arroz Al Cuba (1order=175grams)\tMaincourse
BBQ sauce (1gal=3785grams)\tMaincourse
Bacon (1kl=1000grams)\tSandwich
Bistek Tagalog (1order=100grams)\tMaincourse
Boneless Bangus (1order=150grams)\tMaincourse
Buttercup (1bar=950grams)\tSandwich
Ciabatta Bread (1pack=6pcs)\tSandwich
Cris Fish Fil (1order=200grams)\tMaincourse
Famous Sisig (1order=100grams)\tMaincourse
Feta cheese (1pack=150grams@96pcs)\tSandwich
Fettucine pasta/500g\tSandwich
1pack=10pcs\tSandwich
8pcs=24orders\tSandwich
Italian Lunganigue (1pack=5pcs)\tSandwich
Lechon Kawali (1order=200grams)\tMaincourse
Mag quickmelt  (1pack=950grams)\tSandwich
Mayonnaise (1jar=5.5liters)\tSandwich
Nachos yellow (1pack=25pcs@200grams)\tSandwich
Penne Pasta (1pack=500grams)\tSandwich
Phillys (1order=70grams)\tSandwich
Porkchop (1order=380grams)\tMaincourse
Ribeye Tapsilog (1order = 120grams)\tMaincourse
Salpicao (1order=130grams)\tMaincourse
Slice Mushroom  (1can=850grams)\tSandwich
Spaghetti pasta/900g\tSandwich
Taco plastic (1pack=100pcs)\tSandwich
Taco shell (1pack=12pcs)\tSandwich
Taco stand (1pack=150pcs)\tSandwich
Ube (1kl=1000grams)\tSoda
Whole Cheese (1bar=900 grams)\tSandwich
peeled tomato (1can=800grams)\tSandwich
Ice cream Coffe crumble (1x5L=12scoops)\tSoda
Ice cream Mango (1x3L=32scoops)\tSoda
Ice cream Pistachio cashew (1x5L=12scoops)\tSoda
Ice cream Strawberry (1x3L=32scoops)\tSoda
Ice cream Super chocolate (1x3L=32scoops)\tSoda
Ice cream Ube royale (1x3L=32scoops)\tSoda
Ice cream Vanilla (1x3L=32scoops)\tSoda
Ice cream Very rocky road (1x3L=24scoops)\tSoda
Ice cream cookies &cream (1x3L=24scoops)\tSoda
Banana Split Glass (1pc)\tWarehouse
Beer Mug Tall (1pc)\tWarehouse
Halo-Halo plastic bowl (1pc)\tWarehouse
Halo-halo bowl Glass (1pc)\tWarehouse
Ice Crusher  (1pc)\tWarehouse
Leche plan tray (1pc)\tWarehouse
Nachos plate (1pc)\tWarehouse
Sizzling plate (1pc)\tWarehouse
Sundae glass (1pc)\tWarehouse
Wooden Spoon (1pack=25pcs)\tCounter
8x14 011 Clear Plastic (1pc)\tCounter
COOLERS CUPS (1pack=50pcs)\tCounter
Coolers Cover (1pack)\tCounter
Cups Holder (1pc)\tCounter
DOMELIDS (1pack=100pcs)\tCounter
Halo underliner (1pc)\tWarehouse
Packing Tape (1pc)\tWarehouse
Paper Cups 12oz (1pc)\tCounter
Paper Cups 16oz (1pc)\tCounter
Paper Cups 22oz (1pc)\tCounter
Paper Packlunch 1div (1pc)\tSandwich
Paper Straw (1pack=100pcs)\tCounter
Paper cups flat lids (1pc)\tCounter
Styro for Goods (1pc)\tWarehouse
Take out Cups w/ print (1pack=50pcs)\tCounter
Take out coffee cups 16oz (1pc)\tCoffee Bar
Take out coffee cups 8oz (1pc)\tCoffee Bar
Take out coffee cups lids 16oz (1pc)\tCoffee Bar
Take out coffee cups lids 8oz (1pc)\tCoffee Bar
Wooden Cutlery Set (1pc)\tCounter
Wooden Fork (1pack=25pcs)\tCounter
Wooden Knife/Cutler (1pack=25pcs)\tCounter
Cash Register Tape (1pc)\tCounter
Chairs red (1pc)\tWarehouse
Mask Tape (1pc)\tWarehouse
Record Book (1pc)\tWarehouse
Chairs green (1pc)\tWarehouse
Cheers Pullnaps 2ply (1pc)\tCounter
Cheers Trashbag translucent xxl (1pack)\tCounter
Cheers Trashbag xxl (1pack)\tCounter
Cheers Trashbag xxl(Green) (1pc)\tCounter
Coffee table menu standee (1pc)\tCoffee Bar
Jigger Glass (1pc)\tCoffee Bar
Mop Head #600 (1pc)\tCounter
Precut Tissue (1pc)\tCounter
Rice Cooker  (1pc)\tWarehouse
Stainless powder shaker (1pc)\tCoffee Bar
Trashbag Black (1pc)\tCounter"""

mapping = {}
for line in raw.strip().split('\n'):
    parts = line.strip().split('\t')
    if len(parts) == 2:
        pname = parts[0].strip()
        station = parts[1].strip()
        # Normalize warehouse -> Warehouse
        if station.lower() == 'warehouse':
            station = 'Warehouse'
        mapping[pname] = station

conn = sqlite3.connect('instance/inventory.db')
cursor = conn.cursor()

# Get all DB products
cursor.execute('SELECT id, name, station FROM product ORDER BY name')
db_products = cursor.fetchall()

# Find unmapped
unmapped_in_list = []
for pname, expected_station in mapping.items():
    found = False
    for pid, db_name, db_station in db_products:
        # Normalize for comparison
        clean_list = ' '.join(pname.lower().split())
        clean_db = ' '.join(db_name.lower().split())
        if clean_list == clean_db or pname == db_name or pname.lower() == db_name.lower():
            found = True
            break
    if not found:
        unmapped_in_list.append((pname, expected_station))

print(f'=== Products in your list NOT found in database ({len(unmapped_in_list)}) ===')
for name, station in unmapped_in_list:
    print(f'  "{name}" -> {station}')

# Find DB products without station that are similar to list items
print()
print('=== DB products without station (potential matches from your list) ===')
cursor.execute('SELECT id, name, station FROM product WHERE station IS NULL')
unstationed = cursor.fetchall()
for pid, db_name, _ in unstationed:
    clean_db = ' '.join(db_name.lower().split())
    for list_name, list_station in mapping.items():
        clean_list = ' '.join(list_name.lower().split())
        if clean_db == clean_list or clean_db in clean_list or clean_list in clean_db:
            print(f'  [{pid}] "{db_name}" should be -> {list_station}')
            break

conn.close()
