#include <metal_stdlib>
using namespace metal;
#define BUF_OFFSET 4
// compute texture
#define texture_2d_rw( name, index ) texture2d<float, access::read_write> name [[texture(index)]]
#define texture_2d_r( name, index ) texture2d<float, access::read> name [[texture(index)]]
#define texture_2d_w( name, index ) texture2d<float, access::write> name [[texture(index)]]
#define texture_3d_rw( name, index ) texture3d<float, access::read_write> name [[texture(index)]]
#define texture_3d_r( name, index ) texture3d<float, access::read> name [[texture(index)]]
#define texture_3d_w( name, index ) texture3d<float, access::write> name [[texture(index)]]
#define texture_2d_array_rw( name, index ) texture2d_array<float, access::read_write> name [[texture(index)]]
#define texture_2d_array_r( name, index ) texture2d_array<float, access::read> name [[texture(index)]]
#define texture_2d_array_w( name, index ) texture2d_array<float, access::write> name [[texture(index)]]
#define read_texture( name, gid ) name.read(gid)
#define write_texture( name, val, gid ) name.write(val, gid)
#define read_texture_array( name, gid, slice ) name.read(gid, uint(slice))
#define write_texture_array( name, val, gid, slice ) name.write(val, gid, uint(slice))
// standard texture
#define texture_2d( name, sampler_index ) texture2d<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define texture_3d( name, sampler_index ) texture3d<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define texture_2dms( type, samples, name, sampler_index ) texture2d_ms<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define texture_cube( name, sampler_index ) texturecube<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define texture_2d_array( name, sampler_index ) texture2d_array<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define texture_cube_array( name, sampler_index ) texturecube_array<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define texture_2d_external( name, sampler_index ) texture_2d( name, sampler_index )
// depth texture
#define depth_2d( name, sampler_index ) depth2d<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define depth_2d_array( name, sampler_index ) depth2d_array<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define depth_cube( name, sampler_index ) depthcube<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
#define depth_cube_array( name, sampler_index ) depthcube_array<float> name [[texture(sampler_index)]], sampler sampler_##name [[sampler(sampler_index)]]
// _arg macros are used to pass textures through functions from main
#define texture_2d_arg( name ) thread texture2d<float>& name, thread sampler& sampler_##name
#define texture_2d_external_arg( name ) texture_2d_arg(name)
#define texture_3d_arg( name ) thread texture3d<float>& name, thread sampler& sampler_##name
#define texture_2dms_arg( name ) thread texture2d_ms<float>& name, thread sampler& sampler_##name
#define texture_cube_arg( name ) thread texturecube<float>& name, thread sampler& sampler_##name
#define texture_2d_array_arg( name ) thread texture2d_array<float>& name, thread sampler& sampler_##name
#define texture_cube_array_arg( name ) thread texturecube_array<float>& name, thread sampler& sampler_##name
#define depth_2d_arg( name ) thread depth2d<float>& name, thread sampler& sampler_##name
#define depth_2d_array_arg( name ) thread depth2d_array<float>& name, thread sampler& sampler_##name
#define depth_cube_arg( name ) thread depthcube<float>& name, thread sampler& sampler_##name
#define depth_cube_array_arg( name ) thread depthcube_array<float>& name, thread sampler& sampler_##name
// structured buffers
#define structured_buffer_rw( type, name, index ) device type* name [[buffer(index+BUF_OFFSET)]]
#define structured_buffer_rw_arg( type, name, index ) device type* name [[buffer(index+BUF_OFFSET)]]
#define structured_buffer( type, name, index ) constant type* name [[buffer(index+BUF_OFFSET)]]
#define structured_buffer_arg( type, name, index ) constant type* name [[buffer(index+BUF_OFFSET)]]
// sampler
#define sample_texture( name, tc ) name.sample(sampler_##name, tc)
#define sample_texture_2dms( name, x, y, fragment ) name.read(uint2(x, y), fragment)
#define sample_texture_level( name, tc, l ) name.sample(sampler_##name, tc, level(l))
#define sample_texture_grad( name, tc, vddx, vddy ) name.sample(sampler_##name, tc, gradient3d(vddx, vddy))
#define sample_texture_array( name, tc, a ) name.sample(sampler_##name, tc, uint(a))
#define sample_texture_array_level( name, tc, a, l ) name.sample(sampler_##name, tc, uint(a), level(l))
#define sample_texture_cube_array( name, tc, a ) sample_texture_array(name, tc, a)
#define sample_texture_cube_array_level( name, tc, a, l ) sample_texture_array_level(name, tc, a, l)
// sampler compare / gather
#define sample_depth_compare( name, tc, compare_value ) name.sample_compare(sampler_##name, tc, compare_value, min_lod_clamp(0))
#define sample_depth_compare_array( name, tc, a, compare_value ) name.sample_compare(sampler_##name, tc, uint(a), compare_value, min_lod_clamp(0))
#define sample_depth_compare_cube( name, tc, compare_value ) name.sample_compare(sampler_##name, tc, compare_value, min_lod_clamp(0))
#define sample_depth_compare_cube_array( name, tc, a, compare_value ) name.sample_compare(sampler_##name, tc, uint(a), compare_value, min_lod_clamp(0))
// matrix
#define to_3x3( M4 ) float3x3(M4[0].xyz, M4[1].xyz, M4[2].xyz)
#define from_columns_2x2(A, B) (transpose(float2x2(A, B)))
#define from_rows_2x2(A, B) (float2x2(A, B))
#define from_columns_3x3(A, B, C) (transpose(float3x3(A, B, C)))
#define from_rows_3x3(A, B, C) (float3x3(A, B, C))
#define from_columns_4x4(A, B, C, D) (transpose(float4x4(A, B, C, D)))
#define from_rows_4x4(A, B, C, D) (float4x4(A, B, C, D))
#define mul( A, B ) ((A) * (B))
#define mul_tbn( A, B ) ((B) * (A))
#define unpack_vb_instance_mat( mat, r0, r1, r2, r3 ) mat[0] = r0; mat[1] = r1; mat[2] = r2; mat[3] = r3;
#define to_data_matrix(mat) mat
// clip
#define remap_z_clip_space( d ) (d = d * 0.5 + 0.5)
#define remap_ndc_ray( r ) float2(r.x, r.y)
#define remap_depth( d ) (d)
// defs
#define ddx dfdx
#define ddy dfdy
#define discard discard_fragment()
#define lerp mix
#define frac fract
#define mod(x, y) (x - y * floor(x/y))
#define _pmfx_unroll
#define _pmfx_loop
#define	read3 uint3
#define read2 uint2
// atomics
#define atomic_counter(name, index) structured_buffer_rw(atomic_uint, name, index)
#define atomic_load(atomic, original) original = atomic_load_explicit(&atomic, memory_order_relaxed)
#define atomic_store(atomic, value) atomic_store_explicit(&atomic, value, memory_order_relaxed)
#define atomic_increment(atomic, original) original = atomic_fetch_add_explicit(&atomic, 1, memory_order_relaxed)
#define atomic_decrement(atomic, original) original = atomic_fetch_sub_explicit(&atomic, 1, memory_order_relaxed)
#define atomic_add(atomic, value, original) original = atomic_fetch_add_explicit(&atomic, value, memory_order_relaxed)
#define atomic_subtract(atomic, value, original) original = atomic_fetch_sub_explicit(&atomic, value, memory_order_relaxed)
#define atomic_min(atomic, value, original) original = atomic_fetch_min_explicit(&atomic, value, memory_order_relaxed)
#define atomic_max(atomic, value, original) original = atomic_fetch_max_explicit(&atomic, value, memory_order_relaxed)
#define atomic_and(atomic, value, original) original = atomic_fetch_and_explicit(&atomic, value, memory_order_relaxed)
#define atomic_or(atomic, value, original) original = atomic_fetch_or_explicit(&atomic, value, memory_order_relaxed)
#define atomic_xor(atomic, value, original) original = atomic_fetch_xor_explicit(&atomic, value, memory_order_relaxed)
#define atomic_exchange(atomic, value, original) original = atomic_exchange_explicit(&atomic, value, memory_order_relaxed)
#define threadgroup_barrier() threadgroup_barrier(mem_flags::mem_threadgroup)
#define device_barrier() threadgroup_barrier(mem_flags::mem_device)
#define chebyshev_normalize( V ) (V.xyz / max( max(abs(V.x), abs(V.y)), abs(V.z) ))
#define max3(v) max(max(v.x, v.y),v.z)
#define max4(v) max(max(max(v.x, v.y),v.z), v.w)
#define PI 3.14159265358979323846264
struct light_data
{
    float4 pos_radius;
    float4 dir_cutoff;
    float4 colour;
    float4 data;
};
struct distance_field_shadow
{
    float4x4 world_matrix;
    float4x4 world_matrix_inv;
};
struct area_light_data
{
    float4 corners[4];
    float4 colour;
};
struct c_per_pass_view
{
    float4x4 vp_matrix;
    float4x4 view_matrix;
    float4x4 vp_matrix_inverse;
    float4x4 view_matrix_inverse;
    float4 camera_view_pos;
    float4 camera_view_dir;
};
struct c_src_info
{
    float4 inv_texel_size[8];
};
struct c_filter_kernel
{
    float4 filter_info;
    float4 filter_offset_weight[16];
};
struct vs_output
{
    float4 position;
    float4 texcoord;
};
struct ps_output
{
    float4 colour [[color(0)]];
};
fragment ps_output ps_main(vs_output input [[stage_in]]
, texture_2d( src_texture_0, 0 )
, texture_2d( src_texture_1, 1 )
, constant c_per_pass_view &per_pass_view [[buffer(4)]]
, constant c_src_info &src_info [[buffer(14)]]
, constant c_filter_kernel &filter_kernel [[buffer(6)]])
{
    constant float4& camera_view_pos = per_pass_view.camera_view_pos;
    constant float4& camera_view_dir = per_pass_view.camera_view_dir;
    constant float4* inv_texel_size = &src_info.inv_texel_size[0];
    constant float4& filter_info = filter_kernel.filter_info;
    float4 sss_kernel[25];
    sss_kernel[0] = float4(0.530605, 0.613514, 0.739601, 0);
    sss_kernel[1] = float4(0.000973794, 1.11862e-005, 9.43437e-007, -3);
    sss_kernel[2] = float4(0.00333804, 7.85443e-005, 1.2945e-005, -2.52083);
    sss_kernel[3] = float4(0.00500364, 0.00020094, 5.28848e-005, -2.08333);
    sss_kernel[4] = float4(0.00700976, 0.00049366, 0.000151938, -1.6875);
    sss_kernel[5] = float4(0.0094389, 0.00139119, 0.000416598, -1.33333);
    sss_kernel[6] = float4(0.0128496, 0.00356329, 0.00132016, -1.02083);
    sss_kernel[7] = float4(0.017924, 0.00711691, 0.00347194, -0.75);
    sss_kernel[8] = float4(0.0263642, 0.0119715, 0.00684598, -0.520833);
    sss_kernel[9] = float4(0.0410172, 0.0199899, 0.0118481, -0.333333);
    sss_kernel[10] = float4(0.0493588, 0.0367726, 0.0219485, -0.1875);
    sss_kernel[11] = float4(0.0402784, 0.0657244, 0.04631, -0.0833333);
    sss_kernel[12] = float4(0.0211412, 0.0459286, 0.0378196, -0.0208333);
    sss_kernel[13] = float4(0.0211412, 0.0459286, 0.0378196, 0.0208333);
    sss_kernel[14] = float4(0.0402784, 0.0657244, 0.04631, 0.0833333);
    sss_kernel[15] = float4(0.0493588, 0.0367726, 0.0219485, 0.1875);
    sss_kernel[16] = float4(0.0410172, 0.0199899, 0.0118481, 0.333333);
    sss_kernel[17] = float4(0.0263642, 0.0119715, 0.00684598, 0.520833);
    sss_kernel[18] = float4(0.017924, 0.00711691, 0.00347194, 0.75);
    sss_kernel[19] = float4(0.0128496, 0.00356329, 0.00132016, 1.02083);
    sss_kernel[20] = float4(0.0094389, 0.00139119, 0.000416598, 1.33333);
    sss_kernel[21] = float4(0.00700976, 0.00049366, 0.000151938, 1.6875);
    sss_kernel[22] = float4(0.00500364, 0.00020094, 5.28848e-005, 2.08333);
    sss_kernel[23] = float4(0.00333804, 7.85443e-005, 1.2945e-005, 2.52083);
    sss_kernel[24] = float4(0.000973794, 1.11862e-005, 9.43437e-007, 3);
    ps_output output;
    float2 tc = input.texcoord.xy;
    float z = sample_texture(src_texture_1, tc).r;
    float n = camera_view_pos.w;
    float f = camera_view_dir.w;
    float ez = (2.0 * n * f) / (f + n - z * (f - n));
    float lz = (ez - n) / (f - n);
    float dist = 1.0 / tan(0.5 * 60.0 * 3.14 / 180.0 );
    float scale = dist / lz;
    float w = 1.0;
    float2 final_step = w * scale * filter_info.xy;
    final_step *= 1.0 / 3.0;
    float3 col = sample_texture(src_texture_0, tc).rgb * sss_kernel[0].rgb;
    float2 it = inv_texel_size[0].xy;
    for(int i = 1; i < 25; ++i)
    {
        float2 offset = sss_kernel[i].a * it.xy * final_step;
        col += sample_texture(src_texture_0, (tc + offset)).rgb * sss_kernel[i].rgb;
    }
    output.colour.rgb = col;
    output.colour.a = 1.0;
    return output;
}
