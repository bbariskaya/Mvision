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

add_library(mvision_protocol src/protocol.cpp)
target_include_directories(
    mvision_protocol
    PUBLIC include
    PRIVATE ${MSGPACK_INCLUDE_DIR}
)
target_compile_options(mvision_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)

enable_testing()
add_executable(test_protocol tests/test_protocol.cpp)
target_link_libraries(test_protocol PRIVATE mvision_protocol)
target_compile_options(test_protocol PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME protocol COMMAND test_protocol)

add_library(mvision_pipeline src/image_source_pool.cpp)
target_include_directories(mvision_pipeline PUBLIC include PRIVATE ${DEEPSTREAM_INCLUDE_DIR})
target_link_libraries(
    mvision_pipeline
    PUBLIC PkgConfig::GSTREAMER CUDA::cudart ${NVDS_GST_META_LIBRARY}
)
target_compile_options(mvision_pipeline PRIVATE -Wall -Wextra -Wpedantic -Werror)

add_executable(test_image_ingress tests/test_image_ingress.cpp)
target_link_libraries(test_image_ingress PRIVATE mvision_pipeline)
target_compile_options(test_image_ingress PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(
    NAME image_ingress
    COMMAND test_image_ingress ${CMAKE_CURRENT_SOURCE_DIR}/../../rachel.jpeg
)

add_executable(benchmark_image_ingress tools/benchmark_image_ingress.cpp)
target_link_libraries(benchmark_image_ingress PRIVATE mvision_pipeline)
target_compile_options(benchmark_image_ingress PRIVATE -Wall -Wextra -Wpedantic -Werror)

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

add_library(mvision_yolo_plugin SHARED src/yolo_postprocess_plugin.cpp)
target_include_directories(mvision_yolo_plugin PRIVATE include ${TENSORRT_INCLUDE_DIR})
target_link_libraries(
    mvision_yolo_plugin
    PRIVATE mvision_yolo_postprocess ${TENSORRT_LIBRARY} ${TENSORRT_PLUGIN_LIBRARY}
)
target_compile_options(
    mvision_yolo_plugin
    PRIVATE -Wall -Wextra -Wpedantic -Werror -Wno-deprecated-declarations
)

add_executable(benchmark_yolo_postprocess tools/benchmark_yolo_postprocess.cu)
target_link_libraries(
    benchmark_yolo_postprocess
    PRIVATE mvision_yolo_postprocess CUDA::cudart
)
