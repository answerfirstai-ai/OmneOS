# Link OMNE units into the boot graph.
# The links are files. This does not start a service.
enable_omne_units() {
  local dest="$1"
  local system="${dest}/etc/systemd/system"
  local multi="${system}/multi-user.target.wants"
  local sockets="${system}/sockets.target.wants"
  local unit
  mkdir -p "${multi}" "${sockets}"
  # omne-doctor is pulled in by omne-session. Linking it from multi-user
  # creates an ordering cycle and systemd skips the doctor.
  for unit in \
    omne.target omne-login.service omne-session.service omne-diag.service omne-reboot-listen.service
  do
    if [[ -e "${system}/${unit}" ]]; then
      ln -sfn "/etc/systemd/system/${unit}" "${multi}/${unit}"
    fi
  done
  if [[ -e "${system}/omne-reboot.socket" ]]; then
    ln -sfn "/etc/systemd/system/omne-reboot.socket" "${sockets}/omne-reboot.socket"
  fi
}

# A boot link uses a guest absolute path. Size is read from the rootfs copy.
image_path_ready() {
  local rootfs="$1"
  local required="$2"
  local target resolved
  if [[ -L "${required}" ]]; then
    target="$(readlink "${required}")"
    case "${target}" in
      /*) resolved="${rootfs}${target}" ;;
      *) resolved="$(cd "$(dirname "${required}")" && realpath -m "${target}")" ;;
    esac
    [[ -s "${resolved}" ]]
    return
  fi
  [[ -s "${required}" ]]
}
