/**
 * @file eco_rx.c
 * @brief ECO decoder (Kim, Kim & Cho, IEEE Access 2021), streaming into the panel
 *
 * Mirrors decode() in ShelfKit-Server/shelfkit/eco.py line for line - change both
 * together. The file is one monochrome plane: header, then the chain table items
 * (type, Δi, Δn or Length as α-VarInts), then the concatenated chain codes with the
 * context code of the paper's Table 8.
 *
 * Memory: the decoded plane (5624 bytes) does not fit next to everything else, so
 * it is rebuilt in bands of ECO_BAND_BYTES. Chains only ever walk down, so a band
 * is complete once every chain that STARTS above its end has been traced; the
 * decoder simply runs again from the top for each band, dropping pixels outside
 * it (8 runs, a few hundred ms in all). Each band is then reverse-MTF'd (the
 * running state carries across bands) and shifted out to the panel.
 *
 * B items replay an earlier item's code: a ring of ECO_RING code-reader states
 * (bit position, Table 8 context, pending zero run) and lengths serves that, and
 * the encoder never refers back further than that.
 *
 * Every working value is an XRAM global and no function takes a parameter: the
 * tag's internal RAM is full to the byte (see on_done() in main.c).
 */

#include "eco_rx.h"
#include "epd.h"

#define ECO_W           152u
#define ECO_H           296u
#define ECO_BITS        44992u          /* ECO_W * ECO_H */
#define ECO_RING        32u             /* = RING in eco.py */
#define ECO_BAND_BYTES  760u            /* = BAND_BYTES in eco.py (40 rows) */
#define ECO_BAND_BITS   (ECO_BAND_BYTES * 8u)
#define ECO_OUT_CHUNK   190u            /* epd_stream_write() takes up to 255 */

#define T_A     0
#define T_B     1
#define T_C     2
#define CTX_0   0                       /* previous symbol was 0 */
#define CTX_R   1                       /* previous was a run (R) */
#define CTX_X   2                       /* previous was 1 or 2, or the start */

uint8_t __xdata eco_buf[SM_ECO_MAX];
uint16_t __xdata eco_len;

static uint8_t __xdata band[ECO_BAND_BYTES];
static uint16_t __xdata ring_pos[ECO_RING];
static uint16_t __xdata ring_pend[ECO_RING];
static uint16_t __xdata ring_len[ECO_RING];
static uint8_t __xdata ring_ctx[ECO_RING];

static uint16_t __xdata bit_pos, e_bits;
static uint8_t __xdata e_err, e_alpha, e_most;
static uint16_t __xdata e_count, e_items, e_ccpos;

/* the symbol reader in use (the live chain-code stream, or a replay for a B item) */
static uint8_t __xdata s_ctx;
static uint16_t __xdata s_pend;
/* the live chain-code stream, between items */
static uint16_t __xdata c_pos, c_pend;
static uint8_t __xdata c_ctx;

static uint8_t __xdata g_b, g_k, g_n, g_last, g_s, g_p, g_in, g_out;
static uint16_t __xdata g_v;
static uint16_t __xdata t_pos, idx, cpx, b_start, b_end, n_item, len, k, i;
static uint8_t __xdata e_t, slot, from;

static uint8_t get_bit(void)
{
    if (bit_pos >= e_bits) {
        e_err = 1;
        return 0;
    }
    g_b = eco_buf[bit_pos >> 3] & (uint8_t)(0x80u >> (bit_pos & 7u));
    bit_pos++;
    return g_b ? 1 : 0;
}

/* g_n bits, MSB first (g_n <= 2 here) */
static uint8_t get_bits(void)
{
    g_out = 0;
    while (g_n--) {
        g_out <<= 1;
        g_out |= get_bit();
    }
    return g_out;
}

/* α-VarInt (Fig. 7): chunks of [last flag][α data bits], digits 1..2^α, MSB first */
static uint16_t get_varint(void)
{
    g_v = 0;
    do {
        g_last = get_bit();
        if (g_v > (uint16_t)((0xFFFFu - 16u) >> e_alpha)) {    /* would overflow */
            e_err = 1;
            return 1;
        }
        g_n = e_alpha;
        g_v = (uint16_t)(g_v << e_alpha) + get_bits() + 1u;
    } while (!g_last && !e_err);
    return g_v;
}

/* Table 2 and the per-item type code: the most frequent type is "0", the other two
 * in alphabetical order "10" and "11". */
static uint8_t get_type(void)
{
    if (!get_bit())
        return e_most;
    g_k = get_bit();                    /* 0 = the first of the other two */
    if (e_most == T_A)
        return g_k ? T_C : T_B;
    if (e_most == T_B)
        return g_k ? T_C : T_A;
    return g_k ? T_B : T_A;
}

/* One chain-code symbol, Table 8 (runs of zeros longer than α+3 come as R) */
static uint8_t get_sym(void)
{
    if (s_pend) {
        s_pend--;
        return 0;
    }
    if (s_ctx == CTX_R) {
        g_s = 1 + get_bit();            /* a 0 cannot follow a maximal run */
    } else if (s_ctx == CTX_0) {
        g_s = get_bit();
        if (g_s)
            g_s = 1 + get_bit();
    } else if (!get_bit()) {
        g_s = 0;
    } else if (!get_bit()) {
        s_pend = get_varint() + e_alpha + 2u;   /* run = VarInt + Rmin, this is one */
        s_ctx = CTX_R;
        return 0;
    } else {
        g_s = 1 + get_bit();
    }
    s_ctx = g_s ? CTX_X : CTX_0;
    return g_s;
}

static void set_px(void)                /* pixel cpx, if it is in the band */
{
    if (cpx < b_start)
        return;
    k = cpx - b_start;
    band[k >> 3] |= (uint8_t)(0x80u >> (k & 7u));
}

static void decode_band(void)
{
    for (i = 0; i < ECO_BAND_BYTES; i++)
        band[i] = 0;
    t_pos = e_items;
    c_pos = e_ccpos;
    c_ctx = CTX_X;
    c_pend = 0;
    idx = 0xFFFFu;                      /* Δi of the first item is i + 1 */
    for (n_item = 0; n_item < e_count && !e_err; n_item++) {
        bit_pos = t_pos;
        e_t = get_type();
        idx += get_varint();
        if (idx >= b_end)
            return;                     /* starts are in raster order: done */
        slot = (uint8_t)(n_item & (ECO_RING - 1u));
        cpx = idx;
        set_px();
        if (e_t == T_A) {
            t_pos = bit_pos;
            ring_len[slot] = 0;
            continue;
        }
        if (e_t == T_B) {
            from = (uint8_t)((n_item - get_varint()) & (ECO_RING - 1u));
            t_pos = bit_pos;
            ring_pos[slot] = bit_pos = ring_pos[from];
            ring_ctx[slot] = s_ctx = ring_ctx[from];
            ring_pend[slot] = s_pend = ring_pend[from];
            ring_len[slot] = len = ring_len[from];
        } else {
            len = get_varint();
            t_pos = bit_pos;
            ring_pos[slot] = bit_pos = c_pos;
            ring_ctx[slot] = s_ctx = c_ctx;
            ring_pend[slot] = s_pend = c_pend;
            ring_len[slot] = len;
        }
        for (i = 0; i < len; i++) {
            g_s = get_sym();
            cpx += ECO_W;
            if (g_s == 1)
                cpx--;
            else if (g_s == 2)
                cpx++;
            if (cpx >= b_end) {
                if (e_t == T_C)         /* the shared stream must stay in step */
                    for (i++; i < len; i++)
                        (void)get_sym();
                break;
            }
            set_px();
        }
        if (e_t == T_C) {
            c_pos = bit_pos;
            c_ctx = s_ctx;
            c_pend = s_pend;
        }
    }
}

uint8_t eco_decode(void)
{
    e_bits = eco_len << 3;
    e_err = 0;
    bit_pos = 0;
    g_n = 2;
    e_alpha = get_bits() + 1;
    if (get_varint() != ECO_W || get_varint() != ECO_H)
        return 0;
    if (!get_bit())
        e_most = T_A;
    else
        e_most = get_bit() ? T_C : T_B;
    if (get_varint() != 1)              /* palette size: one colour per file */
        return 0;
    e_count = get_varint() - 1;
    e_items = bit_pos;
    for (n_item = 0; n_item < e_count && !e_err; n_item++) {   /* find the codes */
        e_t = get_type();
        (void)get_varint();
        if (e_t != T_A)
            (void)get_varint();
    }
    e_ccpos = bit_pos;
    if (e_err)
        return 0;

    g_p = 0;                            /* reverse binary MTF state */
    for (b_start = 0; b_start < ECO_BITS; b_start += ECO_BAND_BITS) {
        b_end = b_start + ECO_BAND_BITS;
        if (b_end > ECO_BITS)
            b_end = ECO_BITS;
        decode_band();
        if (e_err)
            return 0;
        len = (b_end - b_start) >> 3;
        for (i = 0; i < len; i++) {
            g_in = band[i];
            g_out = 0;
            for (g_k = 0; g_k < 8; g_k++) {
                if (g_in & 0x80u)
                    g_p ^= 1;
                g_out = (uint8_t)((g_out << 1) | (g_p ^ 1u));   /* 0 = ink */
                g_in <<= 1;
            }
            band[i] = g_out;
        }
        for (i = 0; i < len; i += ECO_OUT_CHUNK)
            epd_stream_write(band + i,
                             (uint8_t)((uint16_t)(len - i) > ECO_OUT_CHUNK ? ECO_OUT_CHUNK
                                                                  : (uint16_t)(len - i)));
    }
    return 1;
}
