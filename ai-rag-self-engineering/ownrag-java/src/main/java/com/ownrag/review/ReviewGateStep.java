package com.ownrag.review;

import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Component;

import com.ownrag.core.Step;
import com.ownrag.core.StepContext;
import com.ownrag.core.StepResult;
import com.ownrag.util.Json;

/**
 * review_gate 步骤（Python 版 ReviewGate 的平移）：入库闸门——
 * 复核未通过（pending / rejected）一律不许写索引。
 */
@Component
public class ReviewGateStep implements Step {

    @Override
    public String type() {
        return "review_gate";
    }

    @Override
    public StepResult run(StepContext ctx, Map<String, Object> params) {
        Map<String, Object> row;
        try {
            row = ReviewStore.getReview(ctx.conn, ctx.docId);
        } catch (Exception e) {
            return StepResult.fail("复核记录读取失败：" + e.getMessage());
        }
        if (row == null) {
            return StepResult.fail("复核记录缺失：管道里应有 prepare_review 且已执行（否则无人看过就入库）");
        }
        String status = String.valueOf(row.get("status"));
        if (ReviewStore.STATUS_APPROVED.equals(status)) {
            return StepResult.okMetrics("gate", "approved", "verdict", String.valueOf(row.get("verdict")));
        }
        if (ReviewStore.STATUS_REJECTED.equals(status)) {
            String note = row.get("note") == null || String.valueOf(row.get("note")).isEmpty()
                    ? "无原因" : String.valueOf(row.get("note"));
            return StepResult.fail("解析产物已驳回，拒绝入库：" + note);
        }
        int blocking = 0;
        StringBuilder blockingDetail = new StringBuilder();
        try {
            List<?> list = Json.MAPPER.readValue(
                    String.valueOf(row.getOrDefault("blocking_json", "[]")),
                    Json.MAPPER.getTypeFactory().constructCollectionType(List.class, Map.class));
            blocking = list.size();
            for (Object o : list) {
                Map<?, ?> b = (Map<?, ?>) o;
                if (blockingDetail.length() > 0) {
                    blockingDetail.append("；");
                }
                blockingDetail.append(b.get("code")).append(":").append(b.get("detail"));
            }
        } catch (Exception ignored) {
            // blocking_json 损坏只影响提示信息，不影响闸门判定
        }
        String verdict = String.valueOf(row.get("verdict"));
        // verdict=fail = 解析产物本身不可用（空正文/字符密度过低）：换后端重传才可能好，
        // 人工点"通过"也救不回来——这类才是真失败，别混进"待复核"。
        if ("fail".equals(verdict)) {
            return StepResult.fail("解析质量检查未通过（阻断项 " + blocking + " 条，"
                    + "换解析后端/修正参数后重传）：" + blockingDetail);
        }
        return StepResult.awaitReview(
                "解析产物待人工复核（自动结论 verdict=" + verdict
                        + "，阻断项 " + blocking + " 条）：到 /ui 的「解析复核」页看产物，通过后本任务自动续跑");
    }
}
