# Copyright 2022 The TensorStore Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Functions to assist in invoking protoc for CMake."""

import io
import os
from typing import List, Optional

from .cmake_builder import CMakeBuilder
from .cmake_builder import quote_list
from .cmake_builder import quote_path
from .evaluation import EvaluationContext
from .label import CMakeTarget
from .label import Label
from .provider import CMakeDepsProvider
from .provider import FilesProvider
from .provider import TargetInfo

PLUGIN_MAPPING = {
    "@com_google_upb//upbc:protoc-gen-upb": ("upb", ".upb"),
    "@com_google_upb//upbc:protoc-gen-upbdefs": ("upbdefs", ".upbdefs"),
    "@com_github_grpc_grpc//src/compiler:grpc_cpp_plugin": ("grpc", ".grpc.pb"),
}


def protoc_compile_protos_impl(
    _context: EvaluationContext,
    _label: Label,
    proto_src: Label,
    plugin: Optional[Label] = None,
    add_files_provider: bool = False,
    flags: Optional[List[str]] = None) -> FilesProvider:
  if flags is None:
    flags = []

  proto_suffix = ".proto"
  assert proto_src.endswith(proto_suffix)
  proto_prefix = proto_src[:-len(proto_suffix)]

  cmake_deps: List[CMakeTarget] = []
  extra_args: List[str] = []

  (plugin_name, ext) = ("cpp", ".pb")
  if plugin is not None:
    cmake_name = _context.get_dep(plugin)
    if len(cmake_name) != 1:
      raise ValueError(f"Resolving {plugin} returned: {cmake_name}")
    (plugin_name, ext) = PLUGIN_MAPPING.get(plugin, ("cpp", ".pb"))
    if plugin_name == "cpp":
      raise ValueError(f"Unknown {plugin}")

    cmake_deps.append(cmake_name[0])
    extra_args.append(
        f'--plugin=protoc-gen-{plugin_name}="$<TARGET_FILE:{cmake_name[0]}>"')

  generated_h = f"{proto_prefix}{ext}.h"
  generated_cc = f"{proto_prefix}{ext}.cc"

  if flags:
    joined_flags = ",".join(flags)
    extra_args.append(
        f"--{plugin_name}_out={joined_flags}:${{PROJECT_BINARY_DIR}}")
  else:
    extra_args.append(f"--{plugin_name}_out=${{PROJECT_BINARY_DIR}}")

  generated_h_path = _context.get_generated_file_path(generated_h)
  generated_cc_path = _context.get_generated_file_path(generated_cc)

  # Add generated file targets.
  protoc_target_pair = _context.generate_cmake_target_pair(
      _label, generate_alias=False)

  protoc_deps = CMakeDepsProvider([protoc_target_pair.target])
  _context.add_analyzed_target(
      generated_h, TargetInfo(FilesProvider([generated_h_path]), protoc_deps))
  _context.add_analyzed_target(
      generated_cc, TargetInfo(FilesProvider([generated_cc_path]), protoc_deps))

  files_provider = FilesProvider([generated_h_path, generated_cc_path])
  if add_files_provider:
    _context.add_analyzed_target(
        _label, TargetInfo(*protoc_target_pair.as_providers(), files_provider))
  else:
    _context.add_analyzed_target(_label,
                                 TargetInfo(*protoc_target_pair.as_providers()))

  # Emit the builder.
  proto_src_files = _context.get_file_paths(proto_src, cmake_deps)
  assert len(proto_src_files) == 1

  # TODO: Resolve the protocol compiler name.
  # protoc_name = _context.get_dep("@com_google_protobuf//:protoc")

  _emit_protoc_generate_cc(
      _context.builder,
      protoc_target_pair.target,
      proto_file_path=proto_src_files[0],
      generated=[generated_h_path, generated_cc_path],
      cmake_deps=cmake_deps,
      extra_args=extra_args,
      comment=f"Running protoc ({plugin_name})"
  )

  return files_provider


def _emit_protoc_generate_cc(
    _builder: CMakeBuilder,
    cmake_target: str,
    proto_file_path: str,
    generated: List[str],
    cmake_deps: List[CMakeTarget],
    extra_args: Optional[List[str]] = None,
    comment="Running protoc",
):
  """Emits CMake to generates a C++ file from a Proto file using protoc."""
  if extra_args is None:
    extra_args = []
  cmake_deps.append("protobuf::protoc")
  cmake_deps.append(proto_file_path)

  out = io.StringIO()
  out.write(f'''
add_custom_command(
  OUTPUT {quote_list(generated)}
  COMMAND protobuf::protoc
  ARGS --experimental_allow_proto3_optional
      -I "${{PROJECT_SOURCE_DIR}}"''')
  for arg in extra_args:
    out.write(f"\n      {arg}")
  out.write(f"""
      {quote_path(proto_file_path)}
  DEPENDS {quote_list(cmake_deps)}
  COMMENT "{comment} on {os.path.basename(proto_file_path)}"
  VERBATIM)
add_custom_target({cmake_target} DEPENDS {quote_list(generated)})
""")
  _builder.addtext(out.getvalue())