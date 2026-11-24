# Projects and workflow canvas

Open [Poke Dev](http://127.0.0.1:7861/work). The project sidebar stays available across Work, Workflow, Results, and Tools. The interface follows the app's light/dark setting.

## Create a reusable project workflow

1. Connect or select a Gitea project.
2. Open **Workflow → Tạo workflow**.
3. Add Developer, Tester, and Reviewer tasks. Select a task to edit its instructions, acceptance criteria, and exact file scope. Connect task handles or use the dependency checkboxes to set the order. Independent branches can run concurrently.
4. In **Kiểm chứng & preview**, configure test/build commands and an optional preview. Existing browser checks remain editable in the JSON section.
5. Save. Incomplete workflows are saved as drafts; the saved status explains what is missing. A ready workflow can be selected for a new requirement.

Use **Dùng cho yêu cầu mới** or choose the workflow in a new requirement's **Workflow sử dụng** field. BA still analyzes the requirement and repository, but the selected canvas supplies the exact task graph, file grants, and checks. The planner does not replace that graph. Review and approve the resulting plan before implementation starts.

## Edit a proposed plan

Before approving a generated plan, select **Chỉnh kế hoạch trên canvas**. Edit and save it, then select **Áp dụng vào kế hoạch**. Return to the plan, review the changes, and approve its new version. An approval for an older version is rejected.

**Lưu thành workflow** copies a run's plan into a reusable canvas, including its verification commands, preview, and browser checks. Completed and running plans remain unchanged when their template is edited. Each run records the workflow name, revision, and digest it used. Concurrent edits from another tab are rejected instead of overwriting a newer save.

## Existing package workflows

The Workflow tab also lists saved package canvases. Open one, choose its project, and use **Tạo công việc từ canvas**. This saves and copies the canvas into a separate project work item. The original template remains reusable. Its existing compiler, approval, and product cycle controls remain in **Công cụ**.

Project workflow canvases use the live project's Developer/Tester/Reviewer runner. Package canvases retain their package compiler and runtime. Both are reachable from the project workspace; they keep their applicable validation and approval rules.

Run history, versioned documents and Memory, parallel agent timelines, tests, previews, patch download, retry/reconciliation, and Gitea branch export are still available from the Work and Results tabs.
