import unittest

import benchmark_lfw_3gpu as benchmark


class LandmarkPayloadTest(unittest.TestCase):
    def test_uses_worker_protocol_landmarks_xy(self):
        face = {"landmarks_xy": [float(value) for value in range(10)]}

        self.assertEqual(
            benchmark.landmark_payload(face),
            {"points": [[0.0, 1.0], [2.0, 3.0], [4.0, 5.0], [6.0, 7.0], [8.0, 9.0]]},
        )


if __name__ == "__main__":
    unittest.main()
