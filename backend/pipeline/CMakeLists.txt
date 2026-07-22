cmake_minimum_required(VERSION 3.19)
project(mvision_worker LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_ARCHITECTURES 75)

find_path(MSGPACK_INCLUDE_DIR msgpack.hpp REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GSTREAMER REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0)
pkg_check_modules(
    GSTREAMER_RTSP_SERVER
    REQUIRED
    IMPORTED_TARGET
    gstreamer-rtsp-server-1.0
)
find_package(CUDAToolkit REQUIRED)
find_path(
    DEEPSTREAM_INCLUDE_DIR
    gstnvdsmeta.h
    PATHS /opt/nvidia/deepstream/deepstream/sources/includes
    REQUIRED
)
find_library(
    NVDS_GST_META_LIBRARY
    nvdsgst_meta
    PATHS /opt/nvidia/deepstream/deepstream/lib
    REQUIRED
)
find_library(
    NVDS_META_LIBRARY
    nvds_meta
    PATHS /opt/nvidia/deepstream/deepstream/lib
    REQUIRED
)

add_library(mvision_protocol src/protocol.cpp)
target_include_directories(
    mvision_protocol
    PUBLIC include
    PRIVATE ${MSGPACK_INCLUDE_DIR}
)
target_compile_options(mvision_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)

enable_testing()
add_executable(test_live_runtime_contract tests/test_live_runtime_contract.cpp)
target_link_libraries(
    test_live_runtime_contract
    PRIVATE PkgConfig::GSTREAMER PkgConfig::GSTREAMER_RTSP_SERVER
)
target_compile_options(
    test_live_runtime_contract PRIVATE -Wall -Wextra -Wpedantic -Werror
)
add_test(NAME live_runtime_contract COMMAND test_live_runtime_contract)

add_library(mvision_live_protocol src/live_protocol.cpp)
target_include_directories(
    mvision_live_protocol
    PUBLIC include
    PRIVATE ${MSGPACK_INCLUDE_DIR}
)
target_compile_options(mvision_live_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(test_live_protocol tests/test_live_protocol.cpp)
target_include_directories(test_live_protocol PRIVATE ${MSGPACK_INCLUDE_DIR})
target_link_libraries(test_live_protocol PRIVATE mvision_live_protocol)
target_compile_options(test_live_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME live_protocol COMMAND test_live_protocol)

add_library(mvision_live_track_state src/live_track_state.cpp)
target_include_directories(mvision_live_track_state PUBLIC include)
target_compile_options(
    mvision_live_track_state PRIVATE -Wall -Wextra -Wpedantic -Werror
)

add_executable(test_live_track_state tests/test_live_track_state.cpp)
target_link_libraries(test_live_track_state PRIVATE mvision_live_track_state)
target_compile_options(
    test_live_track_state PRIVATE -Wall -Wextra -Wpedantic -Werror
)
add_test(NAME live_track_state COMMAND test_live_track_state)

add_library(mvision_live_osd_state src/live_osd_state.cpp)
target_include_directories(mvision_live_osd_state PUBLIC include)
target_link_libraries(
    mvision_live_osd_state PUBLIC mvision_live_protocol mvision_live_track_state
)
target_compile_options(
    mvision_live_osd_state PRIVATE -Wall -Wextra -Wpedantic -Werror
)

add_executable(test_live_osd_state tests/test_live_osd_state.cpp)
target_link_libraries(test_live_osd_state PRIVATE mvision_live_osd_state)
target_compile_options(
    test_live_osd_state PRIVATE -Wall -Wextra -Wpedantic -Werror -UNDEBUG
)
add_test(NAME live_osd_state COMMAND test_live_osd_state)

add_executable(inspect_live_runtime tools/inspect_live_runtime.cpp)
target_link_libraries(
    inspect_live_runtime
    PRIVATE PkgConfig::GSTREAMER PkgConfig::GSTREAMER_RTSP_SERVER
)
target_compile_options(inspect_live_runtime PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(test_protocol tests/test_protocol.cpp)
target_link_libraries(test_protocol PRIVATE mvision_protocol)
target_compile_options(test_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME protocol COMMAND test_protocol)

add_library(mvision_video_protocol src/video_protocol.cpp)
target_include_directories(
    mvision_video_protocol
    PUBLIC include
    PRIVATE ${MSGPACK_INCLUDE_DIR}
)
target_compile_options(mvision_video_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(test_video_protocol tests/test_video_protocol.cpp)
target_link_libraries(test_video_protocol PRIVATE mvision_video_protocol)
target_compile_options(test_video_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME video_protocol COMMAND test_video_protocol)

add_library(mvision_video_pipeline src/video_pipeline.cpp)
target_include_directories(
    mvision_video_pipeline
    PUBLIC include
    PRIVATE ${DEEPSTREAM_INCLUDE_DIR}
)
target_link_libraries(
    mvision_video_pipeline
    PUBLIC
        mvision_video_protocol
        PkgConfig::GSTREAMER
        CUDA::cudart
        ${NVDS_GST_META_LIBRARY}
        ${NVDS_META_LIBRARY}
)
target_compile_options(
    mvision_video_pipeline
    PRIVATE -Wall -Wextra -Wpedantic -Werror -Wno-missing-field-initializers
)

add_executable(test_video_aggregation tests/test_video_aggregation.cpp)
target_link_libraries(test_video_aggregation PRIVATE mvision_video_pipeline)
target_compile_options(test_video_aggregation PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME video_aggregation COMMAND test_video_aggregation)

add_executable(mvision_video_worker src/video_worker_main.cpp)
target_link_libraries(mvision_video_worker PRIVATE mvision_video_pipeline)
target_compile_options(mvision_video_worker PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_library(mvision_live_pipeline src/live_pipeline.cpp)
target_include_directories(
    mvision_live_pipeline
    PUBLIC include
    PRIVATE ${DEEPSTREAM_INCLUDE_DIR}
)
target_link_libraries(
    mvision_live_pipeline
    PUBLIC
        mvision_live_protocol
        mvision_live_track_state
        mvision_live_osd_state
        mvision_video_pipeline
        PkgConfig::GSTREAMER
        PkgConfig::GSTREAMER_RTSP_SERVER
        CUDA::cudart
        ${NVDS_GST_META_LIBRARY}
        ${NVDS_META_LIBRARY}
)
target_compile_options(
    mvision_live_pipeline
    PRIVATE -Wall -Wextra -Wpedantic -Werror -Wno-missing-field-initializers
)

add_executable(smoke_live_pipeline tools/smoke_live_pipeline.cpp)
target_link_libraries(smoke_live_pipeline PRIVATE mvision_live_pipeline)
target_compile_options(smoke_live_pipeline PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(test_live_lifecycle tests/test_live_lifecycle.cpp)
target_link_libraries(test_live_lifecycle PRIVATE mvision_live_pipeline)
target_compile_options(test_live_lifecycle PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME live_lifecycle COMMAND test_live_lifecycle)

add_executable(mvision_live_worker src/live_worker_main.cpp)
add_library(mvision_live_worker_queue src/live_worker_queue.cpp)
target_include_directories(mvision_live_worker_queue PUBLIC include)
target_link_libraries(mvision_live_worker_queue PUBLIC mvision_live_protocol)
target_compile_options(
    mvision_live_worker_queue PRIVATE -Wall -Wextra -Wpedantic -Werror
)
target_link_libraries(
    mvision_live_worker PRIVATE mvision_live_pipeline mvision_live_worker_queue
)
target_compile_options(mvision_live_worker PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(test_live_worker_process tests/test_live_worker_process.cpp)
target_include_directories(test_live_worker_process PRIVATE ${MSGPACK_INCLUDE_DIR})
target_link_libraries(
    test_live_worker_process PRIVATE mvision_live_protocol mvision_live_worker_queue
)
target_compile_options(
    test_live_worker_process PRIVATE -Wall -Wextra -Wpedantic -Werror
)

add_library(mvision_pipeline src/image_source_pool.cpp)
target_include_directories(mvision_pipeline PUBLIC include PRIVATE ${DEEPSTREAM_INCLUDE_DIR})
target_link_libraries(
    mvision_pipeline
    PUBLIC PkgConfig::GSTREAMER CUDA::cudart ${NVDS_GST_META_LIBRARY} ${NVDS_META_LIBRARY}
)
target_compile_options(
    mvision_pipeline
    PRIVATE -Wall -Wextra -Wpedantic -Werror -Wno-missing-field-initializers
)

add_executable(test_image_ingress tests/test_image_ingress.cpp)
target_link_libraries(test_image_ingress PRIVATE mvision_pipeline)
target_compile_options(test_image_ingress PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(
    NAME image_ingress
    COMMAND test_image_ingress ${CMAKE_CURRENT_SOURCE_DIR}/../../rachel.jpeg
)

add_executable(test_detector_pipeline tests/test_detector_pipeline.cpp)
target_link_libraries(test_detector_pipeline PRIVATE mvision_pipeline)
target_compile_options(test_detector_pipeline PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(
    NAME detector_pipeline
    COMMAND
        test_detector_pipeline
        ${CMAKE_CURRENT_SOURCE_DIR}/../../rachel.jpeg
        ${CMAKE_CURRENT_SOURCE_DIR}/../../configs/pgie_yolov8_face.txt
        ${CMAKE_CURRENT_SOURCE_DIR}/../../configs/preprocess_arcface.txt
        ${CMAKE_CURRENT_SOURCE_DIR}/../../configs/sgie_arcface_r50.txt
        1
)

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tools/benchmark_image_ingress.cpp")
    add_executable(benchmark_image_ingress tools/benchmark_image_ingress.cpp)
    target_link_libraries(benchmark_image_ingress PRIVATE mvision_pipeline)
    target_compile_options(benchmark_image_ingress PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_executable(mvision_worker src/worker_main.cpp)
target_link_libraries(mvision_worker PRIVATE mvision_pipeline mvision_protocol)
target_compile_options(mvision_worker PRIVATE -Wall -Wextra -Wpedantic -Werror)

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tools/inspect_detector_pipeline.cpp")
    add_executable(inspect_detector_pipeline tools/inspect_detector_pipeline.cpp)
    target_link_libraries(inspect_detector_pipeline PRIVATE mvision_pipeline)
    target_compile_options(inspect_detector_pipeline PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

add_library(mvision_yolo_postprocess src/yolo_postprocess.cu)
set_target_properties(mvision_yolo_postprocess PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(mvision_yolo_postprocess PUBLIC include)
target_link_libraries(mvision_yolo_postprocess PUBLIC CUDA::cudart)
target_compile_options(
    mvision_yolo_postprocess
    PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:--expt-relaxed-constexpr;-Xcompiler=-Wall,-Wextra,-Werror>
)

add_executable(test_yolo_decode tests/test_yolo_decode.cu)
target_link_libraries(test_yolo_decode PRIVATE mvision_yolo_postprocess CUDA::cudart)
add_test(NAME yolo_decode COMMAND test_yolo_decode)

find_path(
    TENSORRT_INCLUDE_DIR
    NvInfer.h
    PATHS /usr/include/x86_64-linux-gnu
    REQUIRED
)
find_library(TENSORRT_LIBRARY nvinfer REQUIRED)
find_library(TENSORRT_PLUGIN_LIBRARY nvinfer_plugin REQUIRED)

add_library(
    mvision_yolo_plugin
    SHARED
    src/yolo_postprocess_plugin.cpp
    src/yolo_face_parser.cpp
)
target_include_directories(
    mvision_yolo_plugin
    PRIVATE include ${TENSORRT_INCLUDE_DIR} ${DEEPSTREAM_INCLUDE_DIR}
)
target_link_libraries(
    mvision_yolo_plugin
    PRIVATE mvision_yolo_postprocess ${TENSORRT_LIBRARY} ${TENSORRT_PLUGIN_LIBRARY}
)
target_compile_options(
    mvision_yolo_plugin
    PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Werror
        -Wno-deprecated-declarations
        -Wno-missing-field-initializers
        -Wno-unused-parameter
)

add_executable(test_yolo_face_parser tests/test_yolo_face_parser.cpp)
target_include_directories(test_yolo_face_parser PRIVATE include ${DEEPSTREAM_INCLUDE_DIR})
target_link_libraries(test_yolo_face_parser PRIVATE mvision_yolo_plugin CUDA::cudart)
target_compile_options(
    test_yolo_face_parser
    PRIVATE -Wall -Wextra -Wpedantic -Werror -Wno-missing-field-initializers
)
add_test(NAME yolo_face_parser COMMAND test_yolo_face_parser)

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tools/benchmark_yolo_postprocess.cu")
    add_executable(benchmark_yolo_postprocess tools/benchmark_yolo_postprocess.cu)
    target_link_libraries(
        benchmark_yolo_postprocess
        PRIVATE mvision_yolo_postprocess CUDA::cudart
    )
endif()

add_library(mvision_face_alignment src/face_align_kernel.cu)
set_target_properties(mvision_face_alignment PROPERTIES POSITION_INDEPENDENT_CODE ON)
target_include_directories(mvision_face_alignment PUBLIC include)
target_link_libraries(mvision_face_alignment PUBLIC CUDA::cudart)
target_compile_options(
    mvision_face_alignment
    PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:--expt-relaxed-constexpr;-Xcompiler=-Wall,-Wextra,-Werror>
)

add_executable(test_face_alignment tests/test_face_alignment.cu)
target_link_libraries(test_face_alignment PRIVATE mvision_face_alignment CUDA::cudart)
add_test(NAME face_alignment COMMAND test_face_alignment)

find_path(
    NVDSPREPROCESS_INCLUDE_DIR
    nvdspreprocess_interface.h
    PATHS /opt/nvidia/deepstream/deepstream/sources/gst-plugins/gst-nvdspreprocess/include
    REQUIRED
)
find_library(
    NVBUFSURFTRANSFORM_LIBRARY
    nvbufsurftransform
    PATHS /opt/nvidia/deepstream/deepstream/lib
    REQUIRED
)

add_library(mvision_face_preprocess SHARED src/face_preprocess.cpp)
target_include_directories(
    mvision_face_preprocess
    PRIVATE include ${DEEPSTREAM_INCLUDE_DIR} ${NVDSPREPROCESS_INCLUDE_DIR}
)
target_link_libraries(
    mvision_face_preprocess
    PRIVATE
        mvision_face_alignment
        PkgConfig::GSTREAMER
        CUDA::cudart
        ${NVDS_META_LIBRARY}
        ${NVBUFSURFTRANSFORM_LIBRARY}
)
target_compile_options(
    mvision_face_preprocess
    PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Werror
        -Wno-missing-field-initializers
        -Wno-unused-parameter
)
