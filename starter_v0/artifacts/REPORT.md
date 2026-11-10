# Day 03 Lab v2 Report — Research Agent

## Team

- **Tên nhóm:** TrinhThanhTung-2A202603456
- **Thành viên:** Trịnh Thanh Tùng (nhóm trưởng), Nguyễn Khánh Vinh, Đặng Thanh Hải, Hoàng Gia Khiêm.
- **Provider/model cho các run v0–v3:** OpenRouter / `openai/gpt-4o-mini`.

---

# PHẦN A — Giới thiệu agent

## A1. Agent này làm được gì

Research Agent hỗ trợ tìm bài đăng gần đây theo tài khoản hoặc từ khóa, tra cứu thông tin trên web và tin tức, đọc URL, tìm bài nghiên cứu trên arXiv, tra cứu chính sách nội bộ và lấy các bài đang nổi bật trên Hacker News. Agent có thể hỏi lại khi thiếu thông tin, tổng hợp kết quả thành digest và chỉ gửi nội dung lên Telegram sau khi người dùng xác nhận.

**Chạy thử local:** từ thư mục `starter_v0/`, chạy `streamlit run app.py`, rồi mở `http://localhost:8501`.

## A2. Tool agent có

| Tên tool | Làm được gì | Tool nhóm tự thêm? |
|---|---|---|
| `clarify` | Hỏi lại khi yêu cầu thiếu thông tin hoặc cần xác nhận | Không |
| `timeline` | Lấy bài đăng gần đây của một tài khoản | Không |
| `social_search` | Tìm bài đăng trên mạng xã hội theo từ khóa | Không |
| `lookup` | Tìm thông tin chung hoặc tin tức trên web | Không |
| `fetch` | Đọc nội dung từ một URL | Không |
| `format` | Định dạng các kết quả đã thu thập thành digest | Không |
| `send` | Gửi nội dung tới Telegram sau khi người dùng xác nhận | Không |
| `policy` | Tìm trong tài liệu chính sách nội bộ | Không |
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

Các metric dưới đây lấy từ `summary` trong từng run JSON. `case_accuracy` được dùng làm metric tổng hợp trong bảng giả thuyết; các metric khác được liệt kê riêng để thấy thay đổi theo loại lỗi.

| Version theo version log / tên file | Artifact thay đổi theo version log | Giả thuyết | Case accuracy trước → sau | Kết quả | Artifact version ghi trong run JSON | Run file |
|---|---|---|---:|---:|---|---|
| v0 | Baseline | Đo chất lượng ban đầu của starter | — → 0.75 | 15/20 | `v0+peb1c8179815b+t5b22a2476d41` | `runs/v0_B_base_openrouter_20261110T100823016050.json` |
| v1 | `system_prompt.md` | Viết lại prompt để hỏi lại khi thiếu thông tin, không tự gửi hoặc gọi tool ngoài phạm vi, và làm rõ args cho lookup | 0.75 → 0.90 | 18/20 | `v1+p96bc397b006f+taaa8defe599b` | `runs/v1_B_base_openrouter_20261110T104710725977.json` |
| v2 | `tools.yaml` | Làm rõ điều kiện dùng/không dùng tool, quy ước args và yêu cầu xác nhận của send | 0.90 → 0.95 | 19/20 | `v3+pb92fad19f510+t706688b6b063` | `runs/v2_B_base_openrouter_20261110T124529283747.json` |
| v3 | `system_prompt.md` | Khi user đổi nguồn giữa nhiều lượt, chỉ gọi tool của nguồn mới, không tiếp tục nguồn cũ | 0.95 → 1.00 | 20/20 | `v4+p4199db407a01+t706688b6b063` | `runs/v3_B_base_openrouter_20261110T124746449245.json` |

| Version | Tool routing accuracy | Argument accuracy | Multi-turn accuracy |
|---|---:|---:|---:|
| v0 | 0.80 | 0.75 | 1.00 |
| v1 | 0.95 | 0.90 | 0.8333 |
| v2 | 0.95 | 0.95 | 0.8333 |
| v3 | 1.00 | 1.00 | 1.00 |

**Snapshot audit:** v0 và v3 khớp hash prompt/tools trong run JSON. Snapshot hiện lưu của v1 và v2 đã được dựng lại sau khi xử lý xung đột merge; không khớp đầy đủ hash của artifact lịch sử. Vì vậy, các metric và tool call lịch sử được trích từ run JSON; không dùng nội dung snapshot hiện tại của v1/v2 để khẳng định chính xác đầu vào đã chạy. Run JSON vẫn lưu hash của đầu vào tại thời điểm chạy.

**Quy ước nhãn:** hai run cuối có `version` top-level trong JSON lần lượt là `v3` và `v4`, trong khi tên file và version log gọi các lần thử đó là v2 và v3. Bảng dùng nhãn version log/tên file để giữ đúng thứ tự thí nghiệm, đồng thời ghi `artifact_version` nguyên gốc để tránh nhập nhằng.

## B2. Failure Analysis

Các lỗi dưới đây lấy từ `results[*].result.failures` và tool calls trong run JSON.

| Case ID | Failure type | Tool calls thực tế | Lỗi quan sát được | Hướng sửa |
|---|---|---|---|---|
| `R08_out_of_scope` (v0) | `out_of_scope` | `send` | Yêu cầu ngoài phạm vi vẫn bị chuyển thành hành động gửi | Prompt v1 bổ sung ranh giới ngoài phạm vi và không gọi tool khi không phù hợp |
| `R10_missing_handle` (v0) | `missing_info` | `timeline(screenname="sama")` | Agent đoán tài khoản thay vì hỏi người dùng | Prompt yêu cầu `clarify` khi thiếu handle; v1 tăng case accuracy lên 0.90 |
| `R11_missing_url` (v0) | `missing_info` | `fetch(url="https://example.com/article")` | Agent tự tạo URL thay vì hỏi URL cần đọc | Bổ sung quy tắc hỏi lại khi thiếu URL |
| `R12_confirm_before_send` (v0) | `wrong_boundary` | `send(text="Bản tin này")` | Gọi send khi chưa có xác nhận | Làm rõ confirmation trong prompt và tool declaration; v1 còn sai `response_type=text`, v2 trở đi case này đạt |
| `R13_parallel_web_and_tweets` (v0) | `wrong_tool` (nhãn case; mismatch thực tế là args) | `lookup(query="AI news", timeframe="day")` và `social_search(query="AI", ...)` | Lookup dùng query sai và thiếu `topic="news"` | Làm rõ args cho lookup; v1 trở đi không còn lỗi này |
| `M06_switch_tool` (v1, v2) | `wrong_tool` (gọi tool thừa) | `lookup(...)` kèm `social_search(...)` thừa | Sau khi user đổi nguồn, agent vẫn gọi tool của nguồn cũ | v3 thêm quy tắc thay nguồn; run v3 không còn failure |

Diễn biến: v0 có 5 case FAIL, v1 có 2, v2 có 1 và v3 có 0 trên bộ base 20 case.

## B3. Team Eval Cases

`data/eval_group.json` có 10 case (5 single-turn, 5 multi-turn). Trong `runs/` hiện chỉ có các run suite `base`; chưa có run suite `group`. Do đó cột kết quả ghi rõ chưa có bằng chứng chạy, không suy ra kết quả từ base run.

| Case ID | Nội dung kiểm tra | Kỳ vọng | Kết quả hiện có |
|---|---|---|---|
| `G01_hn_routing` | Nhắc Hacker News thì route đúng tool mới | `hn_top` | Chưa có group run |
| `G02_hn_args_best_limit_query` | Chọn best, limit 10 và query AI từ yêu cầu | `hn_top(story_type=best, limit=10, query=AI)` | Chưa có group run |
| `G03_lookup_not_hn` | Tin AI trên web không bị tool HN chiếm | `lookup(query=AI, topic=news, timeframe=week)` | Chưa có group run |
| `G04_confirm_before_send_slack` | Yêu cầu đăng chưa đủ xác nhận thì hỏi lại | `clarify(response_type=yes_no)`; không gọi `send` | Chưa có group run |
| `G05_missing_handle_pronoun` | Đại từ không xác định được tài khoản thì hỏi lại | `clarify(response_type=text)` | Chưa có group run |
| `M_G06_switch_hn_to_twitter` | Đổi từ HN sang Twitter và giữ chủ đề AI | `social_search(query=AI, search_type=Top)` | Chưa có group run |
| `M_G07_hn_correction_limit` | Giữ story type `new`, cập nhật limit thành 3 | `hn_top(story_type=new, limit=3)` | Chưa có group run |
| `M_G08_clarify_then_hn` | Sau khi làm rõ nguồn và bổ sung query/limit, gọi tool HN | `hn_top(query=LLM, limit=3)` | Chưa có group run |
| `M_G09_confirm_then_send` | Sau xác nhận tường minh mới gửi | `send(confirmed=true)` | Chưa có group run |
| `M_G10_out_of_scope_midway` | Yêu cầu cuối là viết code ngoài phạm vi research | Không gọi tool; từ chối | Chưa có group run |

## B4. Live Chat Evidence

Các ví dụ lấy từ transcript thật. Transcript v3 cuối cùng có lượt `exit` bị `provider_error`; lượt đó không được tính là kết quả thành công bên dưới.

| Transcript | Lượt / yêu cầu | Tool call và trạng thái | Ý nghĩa |
|---|---|---|---|
| `transcripts/v3_openrouter_20261110T144352113087.transcript.json` | 4 lượt nghiên cứu trực tiếp | `lookup`, `social_search`, `lookup`, `lookup`; cả 4 lượt `answered` | Bằng chứng chat nhiều lượt với version v3 |
| `transcripts/v3_openrouter_20261110T161134558821.transcript.json` | Lượt 1–2: tìm tweet khi thiếu tài khoản, sau đó user bổ sung Sam Altman | `clarify` → `timeline`; lượt 1 `waiting_for_user`, lượt 2 `answered` | Agent hỏi lại và dùng thông tin vừa được bổ sung |
| Cùng transcript, lượt 3–4 | Yêu cầu đăng Telegram, sau đó user xác nhận rõ | `clarify` → `send`; kết quả send là `sent` | Confirmation xảy ra trước hành động gửi |

## B5. Bonus Evidence

| Hạng mục | Bằng chứng | Điều đã làm / quan sát được | Giới hạn / guardrail |
|---|---|---|---|
| Telegram `send` | `transcripts/v3_openrouter_20261110T161134558821.transcript.json`, lượt 3–4 | Agent hỏi xác nhận rồi gửi; tool result ghi `status=sent` | Không gửi trước khi user xác nhận; UI cũng yêu cầu checkbox xác nhận |
| arXiv / company policy | `tools/papers/TOOL.md`, `tools/paper_text/TOOL.md`, `tools/policy/TOOL.md` | Có tool declaration và hướng dẫn dùng | Không tìm thấy live transcript/run chứng minh các tool này đã chạy end-to-end; không khẳng định đã kiểm thử live |
| UI | `app.py` | Có các trang Chat, so sánh version, so sánh câu trả lời và Telegram; chạy bằng Streamlit local | Dùng localhost, không có link demo công khai trong báo cáo |
| Tool mới `hn_top` | `tools/hacker_news/TOOL.md`, `tests/test_hn_top.py`, `data/eval_group.json` | Có implementation, đăng ký tool, test cho routing registry, args, lọc, fallback URL và lỗi HTTP; eval group có case routing/args | Group eval chưa có run JSON; test của tool không thay thế kết quả routing từ model |
| Unit tests | `tests/test_hn_top.py`, `tests/test_tool_contract.py`, `tests/test_tools_examples.py` | `test_hn_top.py` có 17 hàm test (25 case sau khi mở rộng `parametrize`); đã có ghi nhận 92 tests passed ở các suite HN, contract và examples | Không bao gồm `tests/test_tools_todo.py`; chưa có tổng số bug legacy được ghi lại. Ví dụ test bao phủ HN item thiếu URL phải fallback sang link item HN, điều mà eval routing/args không chấm |

## B6. Reflection

- **Sửa trong `system_prompt.md`:** cách xử lý yêu cầu ngoài phạm vi, hỏi lại khi thiếu thông tin và thay nguồn khi user đổi hướng giữa các lượt.
- **Sửa trong `tools.yaml`:** ranh giới dùng từng tool, convention args và điều kiện `confirmed=true` cho `send`.
- **Cần người dùng duyệt:** trước hành động gửi nội dung ra Telegram. Eval có thể kiểm tra tool/args, nhưng không thay thế xác nhận hành động ngoài hệ thống.
- **Cải thiện tiếp:** chạy `eval_group.json` trên v3 để có kết quả cho 10 case nhóm; giữ snapshot/hash khớp run cho mọi version; bổ sung đánh giá chất lượng nội dung và tính phù hợp của nguồn, không chỉ routing/arguments.

## B7. Small Local Model Challenge (bonus)

**Chưa thực hiện.** Các run hiện có dùng OpenRouter; chưa thấy run Ollama/local hoặc các version `v4-local` / `v5-local`. Vì vậy không có cơ sở để điền bảng cloud/local hay kết luận về lỗi đặc thù của model nhỏ.
