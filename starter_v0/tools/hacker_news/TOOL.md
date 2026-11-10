---
name: hn_top
description: Lấy các bài đang hot trên Hacker News (cộng đồng lập trình viên/tech).
---

# hn_top

Lấy bài đang hot trên Hacker News qua API công khai (không cần key).

## Khi nào dùng
- Người dùng nhắc "Hacker News" hoặc "HN".

## Khi nào KHÔNG dùng
- Tin báo chí chung → `lookup`; Twitter → `social_search` / `timeline`.

## Tham số
- `story_type`: `top` (mặc định) | `new` | `best`
- `query`: lọc theo từ khóa trong tiêu đề
- `limit`: số bài (mặc định 5)

## Kết quả
`{"items": [{"title", "url", "source", "score"}]}`