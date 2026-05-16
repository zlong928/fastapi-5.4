from __future__ import annotations

import hashlib
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import DATA_DIR
from app.db.session import get_db
from app.models import Book, BookProgress, User
from app.schemas.book import BookProgressRead, BookProgressUpdate, BookRead, BookUploadResponse

router = APIRouter(prefix="/books", tags=["books"])

MAX_EPUB_UPLOAD_BYTES = 50 * 1024 * 1024
BOOK_UPLOAD_DIR = DATA_DIR / "uploads" / "books"


def _book_upload_dir() -> Path:
    BOOK_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return BOOK_UPLOAD_DIR


def _validate_epub_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File name is required.")
    if not filename.lower().endswith(".epub"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只支持 EPUB 文件")
    return Path(filename).stem or filename


def _validate_epub_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="打开失败，请确认文件格式正确")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            has_container = "META-INF/container.xml" in names
            has_mimetype = "mimetype" in names and archive.read("mimetype").strip() == b"application/epub+zip"
            if not has_container or not has_mimetype:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="打开失败，请确认文件格式正确")
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="打开失败，请确认文件格式正确") from exc


def _get_book_for_user(db: Session, book_id: int, user: User) -> Book:
    book = db.get(Book, book_id)
    if book is None or (book.user_id is not None and book.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    return book


def _get_progress(db: Session, book_id: int, user_id: int) -> BookProgress | None:
    return db.scalars(
        select(BookProgress).where(
            BookProgress.book_id == book_id,
            BookProgress.user_id == user_id,
        )
    ).first()


@router.post("/upload", response_model=BookUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_book(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookUploadResponse:
    title = _validate_epub_filename(file.filename)
    upload_dir = _book_upload_dir()
    temp_path = upload_dir / f".upload-{datetime.now(timezone.utc).timestamp()}.epub"
    digest = hashlib.sha256()
    size = 0

    try:
        with temp_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_EPUB_UPLOAD_BYTES:
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件过大")
                digest.update(chunk)
                output.write(chunk)

        if size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is empty.")
        _validate_epub_zip(temp_path)

        file_hash = digest.hexdigest()
        existing = db.scalars(
            select(Book).where(
                Book.file_hash == file_hash,
                Book.user_id == current_user.id,
            )
        ).first()
        if existing:
            temp_path.unlink(missing_ok=True)
            return BookUploadResponse(book_id=existing.id, title=existing.title, original_filename=existing.original_filename)

        final_path = upload_dir / f"{file_hash}.epub"
        if final_path.exists():
            temp_path.unlink(missing_ok=True)
        else:
            shutil.move(str(temp_path), final_path)
        relative_path = final_path.relative_to(DATA_DIR).as_posix()
        book = Book(
            user_id=current_user.id,
            title=title,
            original_filename=file.filename,
            file_path=relative_path,
            file_hash=file_hash,
        )
        db.add(book)
        db.commit()
        db.refresh(book)
        return BookUploadResponse(book_id=book.id, title=book.title, original_filename=book.original_filename)
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("", response_model=list[BookRead])
def list_books(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Book]:
    return list(
        db.scalars(
            select(Book)
            .where((Book.user_id == current_user.id) | (Book.user_id.is_(None)))
            .order_by(Book.last_opened_at.desc().nullslast(), Book.created_at.desc())
        )
    )


@router.get("/{book_id}", response_model=BookRead)
def get_book(
    book_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Book:
    return _get_book_for_user(db, book_id, current_user)


@router.get("/{book_id}/file")
def get_book_file(
    book_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    book = _get_book_for_user(db, book_id, current_user)
    path = DATA_DIR / book.file_path
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")
    return FileResponse(path, media_type="application/epub+zip", filename=book.original_filename)


@router.get("/{book_id}/progress", response_model=BookProgressRead | None)
def get_book_progress(
    book_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookProgress | None:
    _get_book_for_user(db, book_id, current_user)
    return _get_progress(db, book_id, current_user.id)


@router.post("/{book_id}/progress", response_model=BookProgressRead)
def save_book_progress(
    book_id: int,
    payload: BookProgressUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BookProgress:
    book = _get_book_for_user(db, book_id, current_user)
    now = datetime.now(timezone.utc)
    progress = _get_progress(db, book_id, current_user.id)
    if progress is None:
        progress = BookProgress(book_id=book_id, user_id=current_user.id)
        db.add(progress)
    progress.location_cfi = payload.location_cfi
    progress.progress_percent = payload.progress_percent
    progress.updated_at = now
    book.last_opened_at = now
    db.commit()
    db.refresh(progress)
    return progress
