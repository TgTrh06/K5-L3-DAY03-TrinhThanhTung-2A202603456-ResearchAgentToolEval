# Day 03 Lab v2 Report — Research Agent

> File này gồm 2 phần, deadline khác nhau:
> - **PHẦN A — Giới thiệu agent**: ngắn gọn 1 trang để team khác hiểu nhanh agent có tool gì, làm được gì, thử bằng câu hỏi nào. **Xong trước 16:30** để làm tài liệu phụ trợ khi demo. Có thể làm thành poster HTML/SVG (`artifacts/poster.html` / `poster.svg`) để show cho team cùng zone.
> - **PHẦN B — Chi tiết / Bằng chứng**: bảng đầy đủ (v0–v3, failure, eval, chat) dựa trên log thật. **Có thể hoàn thiện sau buổi debate để nộp bài.**

## Team

- Team:
- Members:
- Provider/model:

---

# PHẦN A — Giới thiệu agent

## A1. Agent này làm được gì

Research Agent hỗ trợ tìm bài đăng gần đây theo tài khoản hoặc từ khóa, tra cứu thông tin trên web và tin tức, đọc URL, tìm bài nghiên cứu trên arXiv và tra cứu chính sách nội bộ. Agent cũng có thể hỏi lại khi thiếu thông tin, tổng hợp kết quả thành digest hoặc lấy các bài đang hot trên Hacker News.

**Link dùng thử (deploy):**

Đang cập nhật — nhóm chưa có UI/link demo.

## A2. Tool agent có

| Tên tool | Làm được gì | Tool mới nhóm thêm? |
|---|---|---|
| `clarify` | Hỏi lại người dùng khi yêu cầu thiếu thông tin | Không |
| `timeline` | Lấy các bài đăng gần đây của một tài khoản | Không |
| `social_search` | Tìm bài đăng trên mạng xã hội theo từ khóa | Không |
| `lookup` | Tìm thông tin chung hoặc tin tức trên web | Không |
| `fetch` | Đọc nội dung từ một URL | Không |
| `format` | Định dạng các kết quả đã thu thập thành digest | Không |
| `send` | Gửi nội dung tới Telegram sau khi người dùng xác nhận | Không |
| `policy` | Tìm thông tin trong tài liệu chính sách nội bộ | Không |
| `papers` | Tìm bài nghiên cứu trên arXiv | Không |
| `paper_text` | Trích xuất nội dung văn bản từ bài nghiên cứu arXiv | Không |
| `hn_top` | Lấy bài top, mới hoặc nổi bật trên Hacker News; có thể lọc theo từ khóa | Có |

## A3. Câu hỏi mẫu để thử

1. Tìm 5 bài đăng mới nhất của Sam Altman.
2. Tìm tin tức mới trong tuần này về AI agent.
3. Đọc URL này và tóm tắt các ý chính: [dán URL].
4. Tìm các bài nghiên cứu trên arXiv về đánh giá AI agent.
5. Lấy 5 bài đang hot trên Hacker News có nhắc đến AI.

---

# PHẦN B — Chi tiết / Bằng chứng

## B1. Version Evidence

Fill from `artifacts/version_log.csv` and `runs/*.json`.

| Version | Changed Artifact | Hypothesis | Metric Before | Metric After | Run File |
|---|---|---|---:|---:|---|
| v0 | baseline |  |  |  |  |
| v1 |  |  |  |  |  |
| v2 |  |  |  |  |  |
| v3 |  |  |  |  |  |

## B2. Failure Analysis

Use actual failures from `results[*].result.failures`.

| Case ID | Failure Type | Actual Tool Calls | What Failed | Fix |
|---|---|---|---|---|
|  |  |  |  |  |

## B3. Team Eval Cases

List the 10 cases added to `data/eval_group.json` (5 single turn + 5 multi turn).

| Case ID | What It Tests | Expected Tool/Behavior | Result |
|---|---|---|---|
|  |  |  |  |

## B4. Live Chat Evidence

Use `transcripts/*.transcript.json`.

| Turn | User Request | Tool Calls | Version Evidence | Outcome |
|---|---|---|---|---|
|  |  |  |  |  |

## B5. Bonus Evidence

Only fill if your team did bonus.

| Bonus | Evidence File | What Worked | Risk / Guardrail |
|---|---|---|---|
| send (Telegram) |  |  |  |
| arXiv/company policy |  |  |  |
| UI |  |  |  |
| Tool unit tests (`tests/`) | `pytest` output |  |  |

Tool unit tests: số test đã viết, số bug tìm được trong tool có sẵn (nếu có), và một ví dụ lỗi mà unit test bắt được nhưng eval không bắt được.

## B6. Reflection

- Which fixes belonged in `system_prompt.md`?
- Which fixes belonged in `tools.yaml`?
- Which failure needed manual review instead of automatic grading?
- What would you improve next?

## B7. Small Local Model Challenge (bonus)

Only fill if your team did the local model challenge.

| Version | Model (provider) | Prompt/Tools | case_accuracy | tool_routing | argument | multiturn | Run File |
|---|---|---|---|---|---|---|---|
| v3 | (cloud) | v3 |  |  |  |  |  |
| v3-... | (ollama) | v3 |  |  |  |  |  |
| v3-... | (ollama) | v3 |  |  |  |  |  |
| v4-local |  |  |  |  |  |  |  |
| v5-local |  |  |  |  |  |  |  |

Lỗi đặc thù của model nhỏ (đếm từ run JSON):

| Failure Pattern | Count | Example Case | Fix Tried | Helped? |
|---|---|---|---|---|
| wrong / hallucinated tool |  |  |  |  |
| invalid JSON args (`_invalid_json_arguments`) |  |  |  |  |
| no tool call / answered directly |  |  |  |  |
| missed `clarify` |  |  |  |  |
| repeated / unnecessary calls |  |  |  |  |

- Cái gì giúp model nhỏ gọi tool đúng hơn nhất? Bằng chứng?
- Bản prompt tối ưu cho local chạy trên model cloud thì sao?
- Khi nào nhóm sẽ chọn model local thay vì cloud cho agent này?
