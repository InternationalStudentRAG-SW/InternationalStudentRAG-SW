"""
PDF 띄어쓰기 복원(app/core/spacing.py) 확인과 다시 색인.

  python -m evaluate.check_spacing                     # 문서별로 몇 군데 고치는지 + 예시 (DB는 안 바꿈)
  python -m evaluate.check_spacing --show 30           # 예시를 30개까지
  python -m evaluate.check_spacing --diff-file logs/spacing_diff.txt   # 바뀐 줄 전체를 파일로
  python -m evaluate.check_spacing --reindex-changed   # 고칠 곳이 있는 문서만 다시 색인 (DB 백업 후)
  python -m evaluate.check_spacing --reindex "파일명.pdf" ...

다시 색인하면 그 문서의 청크가 새로 만들어진다(chunk_index가 바뀔 수 있음 → 예전 기록의 근거 ID와 다를 수 있음).
다시 색인 전에 chroma_db 폴더를 chroma_db_backup_<시각>으로 통째로 복사한다.
서버(uvicorn)를 끄고 실행할 것 (BM25 색인은 서버 시작 때 DB에서 다시 만든다).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple


def _extract_raw(pdf_path: str) -> List[Tuple[int, str]]:
    """색인과 같은 방식(pymupdf4llm + normalize)으로 페이지별 텍스트를 뽑되 띄어쓰기 복원은 하지 않는다."""
    import fitz
    import pymupdf4llm
    from app.core.knowledge_base import MultilingualSentenceSplitter
    sp = MultilingualSentenceSplitter()
    out = []
    doc = fitz.open(pdf_path)
    for p in range(len(doc)):
        md = pymupdf4llm.to_markdown(doc, pages=[p])
        if len(md.strip()) >= 50:
            out.append((p + 1, sp.normalize_text(md)))
    doc.close()
    return out


def check(doc_dir: Path, show: int, diff_file: str = "") -> Dict[str, int]:
    from app.core.spacing import restore_spacing, spacing_stats
    result: Dict[str, int] = {}
    diff_lines: List[str] = []
    for pdf in sorted(doc_dir.glob("*.pdf")):
        pages = _extract_raw(str(pdf))
        fixed, before, after, examples = 0, [], [], []
        for page, text in pages:
            new, n = restore_spacing(text)
            fixed += n
            before.append(text)
            after.append(new)
            if n:
                for old_line, new_line in zip(text.split("\n"), new.split("\n")):
                    if old_line != new_line:
                        examples.append((page, old_line.strip(), new_line.strip()))
        result[pdf.name] = fixed
        print(f"\n■ {pdf.name}\n  고친 조각 {fixed}개 | 한글 대비 공백 비율 {spacing_stats(''.join(before))} → "
              f"{spacing_stats(''.join(after))}")
        for page, o, n in examples[:show]:
            print(f"  p.{page}  {o[:100]}\n        → {n[:120]}")
        for page, o, n in examples:
            diff_lines += [f"[{pdf.name} p.{page}]", f"- {o}", f"+ {n}", ""]
    if diff_file:
        os.makedirs(os.path.dirname(diff_file) or ".", exist_ok=True)
        with open(diff_file, "w", encoding="utf-8") as f:
            f.write("\n".join(diff_lines))
        print(f"\n바뀐 줄 전체: {diff_file}")
    return result


def reindex(doc_dir: Path, names: List[str]) -> None:
    from app.config import settings
    from app.core.knowledge_base import knowledge_base

    db = Path(settings.chroma_db_path)
    backup = db.parent / f"{db.name}_backup_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copytree(db, backup)
    print(f"DB 백업: {backup}")
    for name in names:
        pdf = doc_dir / name
        if not pdf.exists():
            print(f"[건너뜀] 파일 없음: {name}")
            continue
        before = len(knowledge_base.vector_store.get(where={"source": name})["ids"])
        knowledge_base.vector_store.delete(where={"source": name})
        pages = knowledge_base.splitter.extract_from_pdf(str(pdf))  # 여기서 띄어쓰기 복원이 적용됨
        added = 0
        for page in pages:
            added += knowledge_base.add_document(page["content"], page["metadata"]) or 0
        print(f"[다시 색인] {name}: 청크 {before} → {added}개 ({len(pages)}쪽)")
    print(f"완료. 총 청크 {knowledge_base.get_document_count()}개. 서버를 다시 시작하면 BM25도 새로 만들어진다.")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    from app.config import settings
    ap = argparse.ArgumentParser(description="PDF 띄어쓰기 복원 확인·다시 색인")
    ap.add_argument("--show", type=int, default=8, help="문서별 예시 개수")
    ap.add_argument("--diff-file", default="", help="바뀐 줄 전체를 저장할 파일")
    ap.add_argument("--reindex", nargs="+", metavar="PDF", help="이 문서들을 다시 색인")
    ap.add_argument("--reindex-changed", action="store_true", help="고칠 곳이 있는 문서만 다시 색인")
    a = ap.parse_args()

    doc_dir = Path(settings.document_path)
    if a.reindex:
        reindex(doc_dir, a.reindex)
        return 0
    result = check(doc_dir, a.show, a.diff_file)
    if a.reindex_changed:
        changed = [n for n, c in result.items() if c > 0]
        if not changed:
            print("고칠 문서 없음")
            return 0
        print(f"\n다시 색인할 문서: {changed}")
        reindex(doc_dir, changed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
