#include <math.h>

static inline ImVec2 operator+(const ImVec2& lhs, const ImVec2& rhs)
{
    return ImVec2(lhs.x + rhs.x, lhs.y + rhs.y);
}

namespace ImGui
{
    void ImageRotated(ImTextureID tex_id, ImVec2 center, ImVec2 size, float angle) {
        ImDrawList* draw_list = ImGui::GetWindowDrawList();

        float cos_a = cosf(angle);
        float sin_a = sinf(angle);
        ImVec2 pos[4] = {
            center + ImRotate(ImVec2(-size.x * 0.5f, -size.y * 0.5f), cos_a, sin_a),
            center + ImRotate(ImVec2(+size.x * 0.5f, -size.y * 0.5f), cos_a, sin_a),
            center + ImRotate(ImVec2(+size.x * 0.5f, +size.y * 0.5f), cos_a, sin_a),
            center + ImRotate(ImVec2(-size.x * 0.5f, +size.y * 0.5f), cos_a, sin_a)
        };
        ImVec2 uvs[4] = {
            ImVec2(0.0f, 0.0f),
            ImVec2(1.0f, 0.0f),
            ImVec2(1.0f, 1.0f),
            ImVec2(0.0f, 1.0f)
        };

        draw_list->AddImageQuad(tex_id, pos[0], pos[1], pos[2], pos[3], uvs[0], uvs[1], uvs[2], uvs[3], IM_COL32_WHITE);
    }

    void TextCentred(const c8* text) {
        f32 ww = ImGui::GetWindowWidth();
        f32 tw = ImGui::CalcTextSize(text).x;
        ImGui::SetCursorPosX(ww * 0.5 - tw * 0.5);
        ImGui::Text("%s", text);
    }
}
