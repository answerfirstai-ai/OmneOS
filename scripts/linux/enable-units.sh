# Link OMNE units into the boot graph.
# The links are files. This does not start a service.
enable_omne_units() {
  local dest="$1"
  local system="${dest}/etc/systemd/system"
  local multi="${system}/multi-user.target.wants"
  local sockets="${system}/sockets.target.wants"
  local unit
  mkdir -p "${multi}" "${sockets}"
  for unit in omne.target omne-session.service omne-diag.service omne-doctor.service; do
    if [[ -e "${system}/${unit}" ]]; then
      ln -sfn "/etc/systemd/system/${unit}" "${multi}/${unit}"
    fi
  done
  if [[ -e "${system}/omne-reboot.socket" ]]; then
    ln -sfn "/etc/systemd/system/omne-reboot.socket" "${sockets}/omne-reboot.socket"
  fi
}
