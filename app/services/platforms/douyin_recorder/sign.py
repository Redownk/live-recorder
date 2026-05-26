# sign.py
# 这是对 TypeScript 版 abogus.ts 的 Python 实现
# 原始 Rust 实现来自：https://github.com/hua0512/rust-srec/blob/6444641014ea58628af9b0fa51b099620a01d0d0/crates/platforms/src/extractor/platforms/douyin/abogus.rs

import random
import time
from gmssl import sm3  # pip install gmssl
from typing import List


class StringProcessor:
    @staticmethod
    def to_char_str(byte_arr: List[int]) -> str:
        return "".join(chr(b) for b in byte_arr)

    @staticmethod
    def to_char_array(s: str) -> List[int]:
        return [ord(c) for c in s]

    @staticmethod
    def generate_random_bytes(length: int) -> str:
        result = []
        for _ in range(length):
            rd = random.randint(0, 10000)
            result.append((rd & 255 & 170) | 1)
            result.append((rd & 255 & 85) | 2)
            result.append(((rd >> 8) & 170) | 5)
            result.append(((rd >> 8) & 85) | 40)
        return StringProcessor.to_char_str(result)


class CryptoUtility:
    def __init__(self, salt: str, custom_base64_alphabet: List[str]):
        self.salt = salt
        self.base64_alphabet = [list(s) for s in custom_base64_alphabet]
        self.big_array = [
            121, 243, 55, 234, 103, 36, 47, 228, 30, 231, 106, 6, 115, 95, 78, 101,
            250, 207, 198, 50, 139, 227, 220, 105, 97, 143, 34, 28, 194, 215, 18, 100,
            159, 160, 43, 8, 169, 217, 180, 120, 247, 45, 90, 11, 27, 197, 46, 3, 84, 72,
            5, 68, 62, 56, 221, 75, 144, 79, 73, 161, 178, 81, 64, 187, 134, 117, 186,
            118, 16, 241, 130, 71, 89, 147, 122, 129, 65, 40, 88, 150, 110, 219, 199, 255,
            181, 254, 48, 4, 195, 248, 208, 32, 116, 167, 69, 201, 17, 124, 125, 104, 96,
            83, 80, 127, 236, 108, 154, 126, 204, 15, 20, 135, 112, 158, 13, 1, 188, 164,
            210, 237, 222, 98, 212, 77, 253, 42, 170, 202, 26, 22, 29, 182, 251, 10, 173,
            152, 58, 138, 54, 141, 185, 33, 157, 31, 252, 132, 233, 235, 102, 196, 191,
            223, 240, 148, 39, 123, 92, 82, 128, 109, 57, 24, 38, 113, 209, 245, 2, 119,
            153, 229, 189, 214, 230, 174, 232, 63, 52, 205, 86, 140, 66, 175, 111, 171,
            246, 133, 238, 193, 99, 60, 74, 91, 225, 51, 76, 37, 145, 211, 166, 151, 213,
            206, 0, 200, 244, 176, 218, 44, 184, 172, 49, 216, 93, 168, 53, 21, 183, 41,
            67, 85, 224, 155, 226, 242, 87, 177, 146, 70, 190, 12, 162, 19, 137, 114, 25,
            165, 163, 192, 23, 59, 9, 94, 179, 107, 35, 7, 142, 131, 239, 203, 149, 136,
            61, 249, 14, 156,
        ]

    @staticmethod
    def sm3_to_array(input_data: str or bytes) -> List[int]:
        if isinstance(input_data, str):
            input_bytes = input_data.encode("utf-8")
        else:
            input_bytes = input_data
        digest_hex = sm3.sm3_hash(list(input_bytes))
        return list(bytes.fromhex(digest_hex))

    def add_salt(self, param: str) -> str:
        return param + self.salt

    def params_to_array(self, param: str, add_salt: bool) -> List[int]:
        processed = self.add_salt(param) if add_salt else param
        return CryptoUtility.sm3_to_array(processed)

    def transform_bytes(self, values_list: List[int]) -> List[int]:
        result = []
        index_b = self.big_array[1]
        initial_value = 0
        value_e = 0
        array_len = len(self.big_array)

        for index, val in enumerate(values_list):
            if index == 0:
                initial_value = self.big_array[index_b]
                sum_initial = index_b + initial_value
                self.big_array[1] = initial_value
                self.big_array[index_b] = index_b
            else:
                sum_initial = initial_value + value_e

            sum_idx = sum_initial % array_len
            value_f = self.big_array[sum_idx]
            result.append(val ^ value_f)

            next_idx = (index + 2) % array_len
            value_e = self.big_array[next_idx]
            new_sum_idx = (index_b + value_e) % array_len
            initial_value = self.big_array[new_sum_idx]

            self.big_array[new_sum_idx], self.big_array[next_idx] = \
                self.big_array[next_idx], self.big_array[new_sum_idx]
            index_b = new_sum_idx

        return result

    def base64_encode(self, byte_arr: List[int], selected_alphabet: int) -> str:
        alphabet = self.base64_alphabet[selected_alphabet]
        output = ""
        i = 0
        while i < len(byte_arr):
            b1 = byte_arr[i]
            b2 = byte_arr[i + 1] if i + 1 < len(byte_arr) else 0
            b3 = byte_arr[i + 2] if i + 2 < len(byte_arr) else 0
            combined = (b1 << 16) | (b2 << 8) | b3
            output += alphabet[(combined >> 18) & 63]
            output += alphabet[(combined >> 12) & 63]
            output += alphabet[(combined >> 6) & 63] if i + 1 < len(byte_arr) else ""
            output += alphabet[combined & 63] if i + 2 < len(byte_arr) else ""
            i += 3
        while len(output) % 4 != 0:
            output += "="
        return output

    def abogus_encode(self, values: List[int], selected_alphabet: int) -> str:
        alphabet = self.base64_alphabet[selected_alphabet]
        abogus = ""
        i = 0
        while i < len(values):
            v1 = values[i]
            v2 = values[i + 1] if i + 1 < len(values) else 0
            v3 = values[i + 2] if i + 2 < len(values) else 0
            n = (v1 << 16) | (v2 << 8) | v3
            abogus += alphabet[(n >> 18) & 63]
            abogus += alphabet[(n >> 12) & 63]
            abogus += alphabet[(n >> 6) & 63] if i + 1 < len(values) else ""
            abogus += alphabet[n & 63] if i + 2 < len(values) else ""
            i += 3
        while len(abogus) % 4 != 0:
            abogus += "="
        return abogus

    @staticmethod
    def rc4_encrypt(key: List[int], plaintext: str) -> List[int]:
        S = list(range(256))
        j = 0
        for i in range(256):
            j = (j + S[i] + key[i % len(key)]) & 0xff
            S[i], S[j] = S[j], S[i]

        i = j = 0
        pt_bytes = [ord(c) for c in plaintext]
        ct = []
        for char_val in pt_bytes:
            i = (i + 1) & 0xff
            j = (j + S[i]) & 0xff
            S[i], S[j] = S[j], S[i]
            k = S[(S[i] + S[j]) & 0xff]
            ct.append(char_val ^ k)
        return ct


class BrowserFingerprintGenerator:
    @staticmethod
    def generate_fingerprint(browser_type: str) -> str:
        if browser_type in ["Chrome", "Edge", "Firefox"]:
            return BrowserFingerprintGenerator._generate_fingerprint("Win32")
        elif browser_type == "Safari":
            return BrowserFingerprintGenerator._generate_fingerprint("MacIntel")
        else:
            return BrowserFingerprintGenerator._generate_fingerprint("Win32")

    @staticmethod
    def _generate_fingerprint(platform: str) -> str:
        def rand(min_v, max_v): return random.randint(min_v, max_v)
        inner_w = rand(1024, 1920)
        inner_h = rand(768, 1080)
        outer_w = inner_w + rand(24, 32)
        outer_h = inner_h + rand(75, 90)
        screen_x = 0
        screen_y = [0, 30][rand(0, 1)]
        size_w = rand(1024, 1920)
        size_h = rand(768, 1080)
        avail_w = rand(1280, 1920)
        avail_h = rand(800, 1080)
        return f"{inner_w}|{inner_h}|{outer_w}|{outer_h}|{screen_x}|{screen_y}|0|0|{size_w}|{size_h}|{avail_w}|{avail_h}|{inner_w}|{inner_h}|24|24|{platform}"


class ABogus:
    def __init__(self, fp: str = "", user_agent: str = "", options: List[int] = None):
        salt = "cus"
        character = "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe"
        character2 = "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe"
        character_list = [character, character2]
        self.crypto_utility = CryptoUtility(salt, character_list)
        self.user_agent = (
            user_agent if user_agent else
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
        )
        self.browser_fp = fp if fp else BrowserFingerprintGenerator.generate_fingerprint("Edge")
        self.options = options if options else [0, 1, 14]
        self.page_id = 0
        self.aid = 6383
        self.ua_key = [0x00, 0x01, 0x0e]
        self.sort_index = [
            18, 20, 52, 26, 30, 34, 58, 38, 40, 53, 42, 21, 27, 54, 55, 31, 35,
            57, 39, 41, 43, 22, 28, 32, 60, 36, 23, 29, 33, 37, 44, 45, 59, 46,
            47, 48, 49, 50, 24, 25, 65, 66, 70, 71,
        ]
        self.sort_index2 = [
            18, 20, 26, 30, 34, 38, 40, 42, 21, 27, 31, 35, 39, 41, 43, 22, 28,
            32, 36, 23, 29, 33, 37, 44, 45, 46, 47, 48, 49, 50, 24, 25, 52, 53,
            54, 55, 57, 58, 59, 60, 65, 66, 70, 71,
        ]

    def generate_abogus(self, params: str, body: str):
        ab_dir = {8: 3, 18: 44, 66: 0, 69: 0, 70: 0, 71: 0}

        start_enc = int(time.time() * 1000)
        params_hash1 = self.crypto_utility.params_to_array(params, True)
        array1 = CryptoUtility.sm3_to_array(bytes(params_hash1))
        body_hash1 = self.crypto_utility.params_to_array(body, True)
        array2 = CryptoUtility.sm3_to_array(bytes(body_hash1))
        rc4_ua = CryptoUtility.rc4_encrypt(self.ua_key, self.user_agent)
        ua_b64 = self.crypto_utility.base64_encode(rc4_ua, 1)
        array3 = self.crypto_utility.params_to_array(ua_b64, False)
        end_enc = int(time.time() * 1000)

        ab_dir.update({
            20: (start_enc >> 24) & 255,
            21: (start_enc >> 16) & 255,
            22: (start_enc >> 8) & 255,
            23: start_enc & 255,
            24: start_enc // 0x100000000,
            25: start_enc // 0x10000000000,

            26: (self.options[0] >> 24) & 255,
            27: (self.options[0] >> 16) & 255,
            28: (self.options[0] >> 8) & 255,
            29: self.options[0] & 255,

            30: (self.options[1] // 256) & 255,
            31: self.options[1] % 256,
            32: (self.options[1] >> 24) & 255,
            33: (self.options[1] >> 16) & 255,

            34: (self.options[2] >> 24) & 255,
            35: (self.options[2] >> 16) & 255,
            36: (self.options[2] >> 8) & 255,
            37: self.options[2] & 255,

            38: array1[21],
            39: array1[22],
            40: array2[21],
            41: array2[22],
            42: array3[23],
            43: array3[24],

            44: (end_enc >> 24) & 255,
            45: (end_enc >> 16) & 255,
            46: (end_enc >> 8) & 255,
            47: end_enc & 255,
            48: ab_dir[8],
            49: end_enc // 0x100000000,
            50: end_enc // 0x10000000000,

            51: (self.page_id >> 24) & 255,
            52: (self.page_id >> 16) & 255,
            53: (self.page_id >> 8) & 255,
            54: self.page_id & 255,
            55: self.page_id,
            56: self.aid,
            57: self.aid & 255,
            58: (self.aid >> 8) & 255,
            59: (self.aid >> 16) & 255,
            60: (self.aid >> 24) & 255,

            64: len(self.browser_fp),
            65: len(self.browser_fp),
        })

        sorted_values = [ab_dir.get(i, 0) for i in self.sort_index]
        fp_array = StringProcessor.to_char_array(self.browser_fp)

        ab_xor = 0
        for idx, key in enumerate(self.sort_index2):
            val = ab_dir.get(key, 0)
            ab_xor = val if idx == 0 else ab_xor ^ val

        all_values = sorted_values + fp_array + [ab_xor]
        transformed_values = self.crypto_utility.transform_bytes(all_values)
        random_prefix = [ord(c) for c in StringProcessor.generate_random_bytes(3)]
        final_values = random_prefix + transformed_values
        abogus = self.crypto_utility.abogus_encode(final_values, 0)
        final_params = f"{params}&a_bogus={abogus}"
        return final_params, abogus, self.user_agent, self.browser_fp


if __name__ == "__main__":
    ab = ABogus()
    params = "aid=6383&live_id=1&device_platform=web&language=zh-CN"
    body = ""
    result = ab.generate_abogus(params, body)
    print(result)
