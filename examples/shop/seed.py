"""Fill shop.db with demo data: ``python -m examples.shop.seed``."""

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from sqlalchemy import delete

from tungsten.auth import hash_password
from tungsten.models import Role, RoleAssignment, TungstenBase

from .models import Base, Brand, Category, Customer, Order, OrderItem, OrderStatus, Product, Tag, User, make_engine

FIRST = ["Amit", "Neha", "Rahul", "Priya", "Vikram", "Sneha", "Arjun", "Karan", "Ananya", "Rohan", "Isha", "Kabir",
         "Meera", "Aditya", "Pooja", "Siddharth", "Kavya", "Nikhil", "Riya", "Varun"]
LAST = ["Sharma", "Verma", "Mehta", "Singh", "Rao", "Iyer", "Kapoor", "Malhotra", "Gupta", "Nair", "Reddy", "Joshi"]
CITIES = [("Mumbai", "Maharashtra"), ("Pune", "Maharashtra"), ("Ahmedabad", "Gujarat"), ("Surat", "Gujarat"),
          ("Bengaluru", "Karnataka"), ("New Delhi", "Delhi"), ("Chennai", "Tamil Nadu")]
CATEGORIES = [("Clothing", "shirt"), ("Footwear", "footprints"), ("Accessories", "shopping-bag"),
              ("Electronics", "headphones"), ("Home & Living", "house"), ("Other", "ellipsis")]
PRODUCTS = [
    ("Premium T-Shirt", "Comfortable cotton t-shirt", "Clothing", 1299),
    ("Running Shoes", "Lightweight running shoes", "Footwear", 3499),
    ("Travel Backpack", "Spacious travel backpack", "Accessories", 2999),
    ("Sunglasses", "UV protection sunglasses", "Accessories", 1799),
    ("Denim Jeans", "Classic fit denim jeans", "Clothing", 2499),
    ("Winter Jacket", "Warm and durable jacket", "Clothing", 4999),
    ("Smart Watch", "Feature-rich smartwatch", "Electronics", 6999),
    ("Wireless Headphones", "Noise cancelling headphones", "Electronics", 4499),
    ("Ceramic Mug Set", "Set of 4 handmade mugs", "Home & Living", 899),
    ("Leather Wallet", "Slim genuine leather wallet", "Accessories", 1199),
    ("Yoga Mat", "Non-slip eco yoga mat", "Other", 1499),
    ("Bluetooth Speaker", "Portable waterproof speaker", "Electronics", 2999),
    ("Linen Shirt", "Breathable summer linen shirt", "Clothing", 1899),
    ("Canvas Sneakers", "Everyday canvas sneakers", "Footwear", 1999),
    ("Desk Lamp", "Adjustable LED desk lamp", "Home & Living", 1599),
]
ROLES = {
    "Super Admin": ["*"],
    "Admin": ["users.*", "products.*", "orders.*", "customers.*", "categories.*", "brands.*", "page.settings"],
    "Manager": ["products.*", "orders.*", "customers.*", "categories.view_any", "brands.view_any"],
    "Editor": ["products.view_any", "products.create", "products.update", "categories.*", "brands.*"],
    "Viewer": ["products.view_any", "orders.view_any", "customers.view_any"],
}


def seed(url: str = "sqlite:///shop.db", seed_value: int = 7) -> None:
    rnd = random.Random(seed_value)
    engine, Session = make_engine(url)
    Base.metadata.drop_all(engine)
    TungstenBase.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TungstenBase.metadata.create_all(engine)
    now = dt.datetime.now()

    with Session() as db:
        roles = {name: Role(name=name, permissions=perms, color=color) for (name, perms), color in
                 zip(ROLES.items(), ["danger", "info", "purple", "gray", "warning"])}
        db.add_all(roles.values())

        password = hash_password("password")
        admin = User(name="Kuldeep Gothwal", username="kuldeep", email="admin@example.com", password=password,
                     is_admin=True, is_active=True, department="Operations", created_at=now - dt.timedelta(days=400))
        db.add(admin)
        users = [admin]
        for i in range(48):
            first, last = rnd.choice(FIRST), rnd.choice(LAST)
            users.append(User(
                name=f"{first} {last}", username=f"{first}{last}{i}".lower(), email=f"{first}.{last}{i}@company.com".lower(),
                password=password, phone=f"98{rnd.randint(10000000, 99999999)}", is_active=rnd.random() > 0.15,
                department=rnd.choice(["Operations", "Sales", "Marketing", "Engineering", "Support"]),
                is_admin=i < 3, created_at=now - dt.timedelta(days=rnd.randint(0, 200)),
            ))
        db.add_all(users[1:])
        db.flush()
        db.add(RoleAssignment(role_id=roles["Super Admin"].id, user_id=str(admin.id)))
        for u in users[1:]:
            db.add(RoleAssignment(role_id=roles[rnd.choice(["Admin", "Manager", "Editor", "Viewer", "Viewer"])].id,
                                  user_id=str(u.id)))

        cats = {name: Category(name=name, slug=name.lower().replace(" & ", "-").replace(" ", "-"), icon=icon)
                for name, icon in CATEGORIES}
        db.add_all(cats.values())
        brands = [Brand(name=b) for b in ["Urban Co", "Stride", "Nomad", "Pixel", "Casa"]]
        db.add_all(brands)
        tags = [Tag(name=t) for t in ["new", "sale", "bestseller", "eco", "limited"]]
        db.add_all(tags)

        products = []
        for i, (name, desc, cat, price) in enumerate(PRODUCTS):
            stock = rnd.choice([0, 3, 5, 18, 25, 45, 60, 120])
            p = Product(
                name=name, sku=f"{name[:3].upper()}-{i + 1:03d}", short_description=desc,
                description=f"<p>{desc}. Made with care for everyday use.</p>",
                price=Decimal(price), stock=stock, status=rnd.choice(["published"] * 4 + ["draft"]),
                category=cats[cat], brand=rnd.choice(brands), color=rnd.choice(["#ec5b1d", "#111827", "#2563eb", None]),
                sizes=rnd.sample(["S", "M", "L", "XL"], 2) if cat == "Clothing" else None,
                keywords=rnd.sample(["cotton", "summer", "casual", "sale"], 2),
                is_featured=rnd.random() > 0.7, available_from=dt.date.today() - dt.timedelta(days=rnd.randint(0, 90)),
                created_at=now - dt.timedelta(days=rnd.randint(0, 200)),
            )
            p.tags = rnd.sample(tags, 2)
            products.append(p)
        db.add_all(products)

        customers = []
        for i in range(30):
            first, last = rnd.choice(FIRST), rnd.choice(LAST)
            city, state = rnd.choice(CITIES)
            customers.append(Customer(name=f"{first} {last}", email=f"{first}.{last}.{i}@mail.com".lower(),
                                      phone=f"9{rnd.randint(100000000, 999999999)}", city=city, state=state,
                                      created_at=now - dt.timedelta(days=rnd.randint(0, 360))))
        db.add_all(customers)
        db.flush()

        for i in range(120):
            created = now - dt.timedelta(days=rnd.randint(0, 330), hours=rnd.randint(0, 23))
            order = Order(number=f"ORD-{i + 1:04d}", customer=rnd.choice(customers), created_at=created,
                          status=rnd.choice(list(OrderStatus)), shipping_address="221B Example Street")
            total = Decimal(0)
            for sort, product in enumerate(rnd.sample(products, rnd.randint(1, 3))):
                qty = rnd.randint(1, 4)
                order.items.append(OrderItem(product=product, quantity=qty, unit_price=product.price, sort=sort))
                total += product.price * qty
            order.total = total
            db.add(order)
        db.commit()
    print("Seeded demo data. Sign in with admin@example.com / password")  # noqa: T201


if __name__ == "__main__":
    seed()
