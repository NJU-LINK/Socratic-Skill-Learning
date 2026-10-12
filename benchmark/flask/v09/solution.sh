#!/bin/bash
set -uo pipefail

cat > /app/solve.py <<'PYEOF'
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////app/catalog.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    products = db.relationship("Product", back_populates="category")


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    category = db.relationship("Category", back_populates="products")


def _product_json(product):
    return {
        "id": product.id,
        "name": product.name,
        "price": product.price,
        "stock": product.stock,
        "category_id": product.category_id,
        "category_name": product.category.name,
    }


@app.get("/setup")
def setup():
    db.create_all()
    if Category.query.count() == 0:
        categories = [
            Category(name="Electronics", description="Electronic devices"),
            Category(name="Books", description="Printed and digital books"),
            Category(name="Clothing", description="Apparel"),
        ]
        db.session.add_all(categories)
        db.session.flush()
        seeds = {
            "Electronics": [
                ("Phone", 699.0, 15),
                ("Laptop", 1299.0, 6),
                ("Headphones", 149.0, 0),
            ],
            "Books": [
                ("Novel", 15.0, 30),
                ("Textbook", 90.0, 8),
                ("Cookbook", 25.0, 12),
            ],
            "Clothing": [
                ("T-Shirt", 20.0, 50),
                ("Jeans", 55.0, 20),
                ("Jacket", 95.0, 4),
            ],
        }
        for category in categories:
            for name, price, stock in seeds[category.name]:
                db.session.add(
                    Product(
                        name=name,
                        price=price,
                        stock=stock,
                        category_id=category.id,
                    )
                )
        db.session.commit()
    return jsonify({"status": "ok"})


@app.get("/categories")
def categories():
    return jsonify(
        [
            {
                "id": category.id,
                "name": category.name,
                "description": category.description,
                "product_count": len(category.products),
            }
            for category in Category.query.order_by(Category.id).all()
        ]
    )


@app.get("/products")
def products():
    query = Product.query
    try:
        if request.args.get("category_id") is not None:
            query = query.filter(Product.category_id == int(request.args["category_id"]))
        if request.args.get("min_price") is not None:
            query = query.filter(Product.price >= float(request.args["min_price"]))
        if request.args.get("max_price") is not None:
            query = query.filter(Product.price <= float(request.args["max_price"]))
    except ValueError:
        return jsonify({"error": "Invalid filter"}), 400
    if request.args.get("in_stock", "").lower() == "true":
        query = query.filter(Product.stock > 0)
    return jsonify([_product_json(product) for product in query.order_by(Product.id).all()])


@app.get("/products/stats")
def product_stats():
    products = Product.query.all()
    if not products:
        return jsonify(
            {
                "total_products": 0,
                "total_categories": Category.query.count(),
                "avg_price": 0,
                "total_stock": 0,
                "cheapest": None,
                "most_expensive": None,
            }
        )
    cheapest = min(products, key=lambda product: product.price)
    most_expensive = max(products, key=lambda product: product.price)
    return jsonify(
        {
            "total_products": len(products),
            "total_categories": Category.query.count(),
            "avg_price": round(sum(product.price for product in products) / len(products), 2),
            "total_stock": sum(product.stock for product in products),
            "cheapest": {"name": cheapest.name, "price": cheapest.price},
            "most_expensive": {
                "name": most_expensive.name,
                "price": most_expensive.price,
            },
        }
    )


@app.get("/products/<int:product_id>")
def product(product_id):
    item = db.session.get(Product, product_id)
    if item is None:
        return jsonify({"error": "Product not found"}), 404
    result = _product_json(item)
    result.pop("category_name")
    result["category"] = {
        "id": item.category.id,
        "name": item.category.name,
        "description": item.category.description,
    }
    return jsonify(result)


@app.post("/products")
def create_product():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Missing required fields"}), 400
    required = ("name", "price", "stock", "category_id")
    if any(field not in data for field in required):
        return jsonify({"error": "Missing required fields"}), 400

    name = data["name"]
    price = data["price"]
    stock = data["stock"]
    category_id = data["category_id"]
    if (
        not isinstance(name, str)
        or not name
        or not isinstance(price, (int, float))
        or isinstance(price, bool)
        or price < 0
        or not isinstance(stock, int)
        or isinstance(stock, bool)
        or stock < 0
        or not isinstance(category_id, int)
        or isinstance(category_id, bool)
    ):
        return jsonify({"error": "Invalid product fields"}), 400
    category = db.session.get(Category, category_id)
    if category is None:
        return jsonify({"error": "Invalid category_id"}), 400

    item = Product(name=name, price=float(price), stock=stock, category_id=category_id)
    db.session.add(item)
    db.session.commit()
    return jsonify(_product_json(item)), 201
PYEOF
