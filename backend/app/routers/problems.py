"""Report-a-problem per order (F6, Oct 2026).

Customers file a problem report on one of their orders (optionally tied to
a single order line, with an optional photo and a desired outcome).
PRIVATE: visible to the order's vendor + the site admin only — never
public. The admin changes status via /api/admin/problem-reports.
"""
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, models, schemas
from ..database import get_db
from ..photo_uploads import delete_uploaded_file, save_uploaded_photo
from ..ratelimit import check_rate_limit

router = APIRouter(prefix="/api/problems", tags=["order-problems"])


def _out(p: models.OrderProblem, db: Session) -> schemas.OrderProblemOut:
    order = db.get(models.Order, p.order_id)
    dish_name = None
    if p.order_item_id:
        item = db.get(models.OrderItem, p.order_item_id)
        dish_name = item.dish_name if item else None
    vendor_name = order.vendor.name if order and order.vendor else None
    customer = db.get(models.User, p.customer_id)
    return schemas.OrderProblemOut(
        id=p.id,
        order_id=p.order_id,
        order_item_id=p.order_item_id,
        category=p.category,
        description=p.description,
        photo_url=p.photo_url,
        desired_outcome=p.desired_outcome,
        status=p.status,
        created_at=p.created_at,
        dish_name=dish_name,
        vendor_name=vendor_name,
        customer_name=customer.name if customer else None,
    )


def _own_order_or_403(order: models.Order, user: models.User) -> None:
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.customer_id != user.id:
        # Guests (customer_id NULL) cannot file problem reports from the app
        # — only the order's logged-in customer can.
        raise HTTPException(status_code=403, detail="You can only report problems on your own orders")


@router.post("", response_model=schemas.OrderProblemOut, status_code=201)
def create_problem(
    payload: schemas.OrderProblemCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """File a problem report. Only the order's own customer may file."""
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can report problems")
    check_rate_limit(request, "problem_create", limit=30, window_seconds=3600)
    order = db.get(models.Order, payload.order_id)
    _own_order_or_403(order, user)
    if payload.order_item_id is not None:
        item = db.get(models.OrderItem, payload.order_item_id)
        if item is None or item.order_id != order.id:
            raise HTTPException(status_code=404, detail="Order item not found on this order")
    problem = models.OrderProblem(
        order_id=order.id,
        order_item_id=payload.order_item_id,
        customer_id=user.id,
        category=payload.category,
        description=payload.description,
        desired_outcome=payload.desired_outcome,
        status="new",
    )
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return _out(problem, db)


@router.post("/{problem_id}/photo", response_model=schemas.OrderProblemOut)
def attach_problem_photo(
    problem_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Attach (or replace) the problem's photo. Only the reporting customer."""
    problem = db.get(models.OrderProblem, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem report not found")
    if problem.customer_id != user.id:
        raise HTTPException(status_code=403, detail="Not your problem report")
    # Same disk-fill guard as review/dish photo uploads: 20/hour per IP.
    check_rate_limit(request, "problem_photo_upload", limit=20, window_seconds=3600)
    new_url = save_uploaded_photo(file)
    delete_uploaded_file(problem.photo_url)
    problem.photo_url = new_url
    db.commit()
    db.refresh(problem)
    return _out(problem, db)


@router.get("/mine", response_model=list[schemas.OrderProblemOut])
def my_problems(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """The logged-in customer's own problem reports."""
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Customers only")
    stmt = (
        select(models.OrderProblem)
        .where(models.OrderProblem.customer_id == user.id)
        .order_by(models.OrderProblem.created_at.desc())
    )
    if status:
        stmt = stmt.where(models.OrderProblem.status == status.strip().lower())
    return [_out(p, db) for p in db.scalars(stmt).all()]


@router.get("/vendor", response_model=list[schemas.OrderProblemOut])
def vendor_problems(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Problem reports on the vendor's own shop orders. Vendors see their
    shops' reports; admins see everything here too (the back-office uses
    /api/admin/problem-reports for the status changer)."""
    if user.role not in ("vendor", "admin"):
        raise HTTPException(status_code=403, detail="Vendors and admins only")
    stmt = (
        select(models.OrderProblem)
        .join(models.Order, models.Order.id == models.OrderProblem.order_id)
        .order_by(models.OrderProblem.created_at.desc())
    )
    if user.role == "vendor":
        vendor_ids = [v.id for v in user.vendors]
        if not vendor_ids:
            return []
        stmt = stmt.where(models.Order.vendor_id.in_(vendor_ids))
    if status:
        stmt = stmt.where(models.OrderProblem.status == status.strip().lower())
    return [_out(p, db) for p in db.scalars(stmt).all()]
